"""Persistent cache, circuit breaker and quota accounting. Calls run under the global DB lease."""

import asyncio
import hashlib
import json
import logging
from copy import deepcopy
import math
import os
import random
import time
from dataclasses import asdict
from datetime import date, datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
import httpx
from app.models import ProviderState, QueryCache
from app.providers.base import ProviderOffer

logger = logging.getLogger(__name__)

FAMILIES = {
    "flightpowers": "google_flights",
    "serpapi": "google_flights",
    "datacrawler": "google_flights",
    "fast_flights": "google_flights",
    "google_browser": "google_flights",
    "kiwi": "kiwi",
    "flightfinder": "kiwi",
    "travelpayouts": "aviasales",
    "amadeus": "amadeus",
    "ryanair": "ryanair",
    "mock": "demo",
}
EXPERIMENTAL = {"ryanair", "flightfinder", "fast_flights", "google_browser"}
ORDER = [
    "travelpayouts",
    "ryanair",
    "flightfinder",
    "amadeus",
    "kiwi",
    "flightpowers",
    "serpapi",
    "datacrawler",
    "fast_flights",
    "google_browser",
    "mock",
]


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def integer_env(key, default):
    try:
        return max(0, int(os.getenv(key, str(default))))
    except ValueError:
        return default


def supports(p, q):
    if hasattr(p, "supports"):
        return p.supports(q)
    # These APIs currently don't carry all passenger/cabin parameters.
    if p.name in ("flightpowers", "travelpayouts"):
        return q.adults == 1 and q.cabin == "economy"
    return True


def valid(offers, q, search):
    out = []
    for o in offers:
        try:
            if (
                isinstance(o.price, bool)
                or not math.isfinite(o.price)
                or o.price <= 0
                or o.price >= 100_000_000
            ):
                continue
            if (
                o.origin,
                o.destination,
                o.departure_date,
                o.return_date,
                o.currency,
            ) != (q.origin, q.destination, q.departure_date, q.return_date, q.currency):
                continue
            if o.stops is not None and (
                isinstance(o.stops, bool) or not isinstance(o.stops, int) or o.stops < 0
            ):
                continue
            if o.duration_minutes is not None and (
                isinstance(o.duration_minutes, bool)
                or not isinstance(o.duration_minutes, int)
                or o.duration_minutes <= 0
            ):
                continue
            if q.max_stops is not None and (o.stops is None or o.stops > q.max_stops):
                continue
            if search.require_complete_trip and not o.raw.get("_complete_trip"):
                continue
            if search.max_price and o.price > float(search.max_price):
                continue
            if search.max_duration_minutes and (
                o.duration_minutes is None
                or o.duration_minutes > search.max_duration_minutes
            ):
                continue
            if search.airlines and not any(
                a.casefold() in " ".join(o.airlines).casefold() for a in search.airlines
            ):
                continue
            if o.booking_url and urlparse(o.booking_url).scheme not in (
                "http",
                "https",
            ):
                o.booking_url = None
            # Unverified outbound-only and cached fares cannot trigger BUY.
            if o.provider != "flightpowers":
                o.live = False
            out.append(o)
        except (TypeError, ValueError):
            continue
    return out


class Engine:
    def __init__(self, db, search, selected):
        self.db, self.search = db, search
        self.selected = sorted(
            selected, key=lambda p: ORDER.index(p.name) if p.name in ORDER else 99
        )
        self.calls = 0
        self.started = time.monotonic()
        self.deadline = self.started + integer_env("SEARCH_TIMEOUT_SECONDS", 120)
        self.trace = []
        self.usage = {
            p.name: {
                "requests": 0,
                "cache_hits": 0,
                "skipped": 0,
                "errors": 0,
                "limit_per_run": min(
                    integer_env(
                        p.name.upper() + "_MAX_CALLS_PER_RUN",
                        integer_env("PROVIDER_MAX_CALLS_PER_RUN", 10),
                    ),
                    getattr(p, "limit", 300),
                ),
            }
            for p in selected
        }

    def event(self, p, q, status, **extra):
        logger.debug(
            "Provider %s %s -> %s: %s", p.name, q.origin, q.destination, status
        )
        if status == "error":
            logger.warning(
                "Provider %s failed: %s", p.name, extra.get("error", "unknown")
            )
        self.trace.append(
            dict(
                provider=p.name,
                origin=q.origin,
                destination=q.destination,
                departure=str(q.departure_date),
                return_date=str(q.return_date),
                status=status,
                **extra,
            )
        )

    async def query(self, q):
        found = []
        pending = []

        def accept(p, offers):
            accepted = valid(offers, q, self.search)
            if offers and not accepted:
                self.event(p, q, "filtered", results=len(offers))
            found.extend(accepted)
            return any(
                o.provider not in ("travelpayouts", "ryanair")
                and o.raw.get("_environment") != "test"
                for o in accepted
            )

        # Inspect all compatible fresh caches before paying for any adapter.
        for p in self.selected:
            if not supports(p, q):
                self.event(p, q, "unsupported")
                self.usage[p.name]["skipped"] += 1
                continue
            cached = await self.call(p, q, cache_only=True)
            if cached is None:
                pending.append(p)
            elif accept(p, cached) and self.search.strategy == "waterfall":
                return found
        for p in pending:
            if time.monotonic() >= self.deadline:
                self.event(p, q, "deadline")
                break
            if accept(p, await self.call(p, q)) and self.search.strategy == "waterfall":
                break
        return found

    async def call(self, p, q, cache_only=False):
        now = datetime.now(timezone.utc)
        usage = self.usage[p.name]
        key = hashlib.sha256(
            json.dumps(
                {
                    "v": 2,
                    "provider": p.name,
                    "environment": getattr(p, "production", None),
                    "q": asdict(q),
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        cached = self.db.get(QueryCache, key)
        if cached and utc(cached.expires_at) > now:
            try:
                offers = []
                for row in cached.payload:
                    row = {
                        **row,
                        "departure_date": date.fromisoformat(row["departure_date"]),
                        "return_date": date.fromisoformat(row["return_date"]),
                    }
                    row["raw"] = {
                        **row["raw"],
                        "_cached": True,
                        "_observed_at": utc(cached.observed_at).isoformat(),
                    }
                    row["live"] = False
                    offers.append(ProviderOffer(**row))
                usage["cache_hits"] += 1
                self.event(p, q, "cache_hit", results=len(offers))
                return offers
            except (KeyError, TypeError, ValueError):
                self.db.delete(cached)
                self.db.commit()
                cached = None
        if cache_only:
            return None
        state = self.db.get(ProviderState, p.name)
        if state is None:
            state = ProviderState(
                name=p.name, month=now.strftime("%Y-%m"), calls=0, failures=0
            )
            self.db.add(state)
            self.db.commit()
        if state.month != now.strftime("%Y-%m"):
            state.month = now.strftime("%Y-%m")
            state.calls = 0
            self.db.commit()
        if state.blocked_until and utc(state.blocked_until) > now:
            usage["skipped"] += 1
            self.event(p, q, "circuit_open", until=utc(state.blocked_until).isoformat())
            return []
        for attempt in range(2):
            if (
                self.calls >= self.search.max_provider_calls
                or usage["requests"] >= usage["limit_per_run"]
                or state.calls
                >= integer_env(
                    p.name.upper() + "_MONTHLY_CALL_LIMIT",
                    integer_env("PROVIDER_MONTHLY_CALL_LIMIT", 500),
                )
            ):
                usage["skipped"] += 1
                self.event(p, q, "budget_exhausted")
                return []
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self.event(p, q, "deadline")
                return []
            # Commit reservation before network IO so a crash still consumes budget.
            self.calls += 1
            usage["requests"] += 1
            state.calls += 1
            self.db.commit()
            try:
                rows = await asyncio.wait_for(
                    p.search(q),
                    timeout=min(remaining, integer_env("PROVIDER_TIMEOUT_SECONDS", 25)),
                )
                # Validate before cache serialization; bad prices must not poison cache.
                rows = [
                    deepcopy(o)
                    for o in rows
                    if isinstance(o.price, (int, float))
                    and not isinstance(o.price, bool)
                    and math.isfinite(o.price)
                    and 0 < o.price < 100_000_000
                ]
                now = datetime.now(timezone.utc)
                for o in rows:
                    o.raw = {
                        **o.raw,
                        "_observed_at": now.isoformat(),
                        "_family": FAMILIES.get(p.name, p.name),
                    }
                payload = json.loads(
                    json.dumps([asdict(o) for o in rows], default=str, allow_nan=False)
                )
                entry = cached or QueryCache(key=key, provider=p.name)
                entry.payload = payload
                entry.observed_at = now
                entry.expires_at = now + timedelta(
                    seconds=integer_env("CACHE_TTL_SECONDS", 900) if rows else 60
                )
                self.db.add(entry)
                state.failures = 0
                state.last_error = None
                state.blocked_until = None
                self.db.commit()
                self.event(
                    p,
                    q,
                    "ok" if rows else "empty",
                    results=len(rows),
                    attempt=attempt + 1,
                )
                return rows
            except (
                httpx.HTTPStatusError,
                httpx.TransportError,
                TimeoutError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                ImportError,
            ) as exc:
                status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                error = f"HTTP {status}" if status else type(exc).__name__
                retryable = isinstance(exc, (httpx.TransportError, TimeoutError)) or (
                    status is not None and status >= 500
                )
                seconds = 0
                if status in (401, 403):
                    seconds = 3600
                if status == 429:
                    seconds = 300
                    value = exc.response.headers.get("Retry-After", "")
                    try:
                        seconds = max(seconds, int(value))
                    except ValueError:
                        try:
                            seconds = max(
                                seconds,
                                int(
                                    (
                                        parsedate_to_datetime(value)
                                        - datetime.now(timezone.utc)
                                    ).total_seconds()
                                ),
                            )
                        except (ValueError, TypeError, OverflowError):
                            pass
                state.failures += 1
                state.last_error = error
                usage["errors"] += 1
                if state.failures >= 3:
                    seconds = max(seconds, 300)
                if seconds:
                    state.blocked_until = datetime.now(timezone.utc) + timedelta(
                        seconds=min(seconds, 86400)
                    )
                self.db.commit()
                self.event(p, q, "error", error=error, attempt=attempt + 1)
                if not retryable or attempt == 1 or seconds:
                    return []
                await asyncio.sleep(
                    min(
                        max(0, self.deadline - time.monotonic()),
                        0.3 + random.random() * 0.4,
                    )
                )
            except Exception as exc:
                # Third-party libraries expose custom errors; never log URLs/tokens.
                state.failures += 1
                state.last_error = type(exc).__name__
                usage["errors"] += 1
                if state.failures >= 3:
                    state.blocked_until = datetime.now(timezone.utc) + timedelta(
                        seconds=300
                    )
                self.db.commit()
                self.event(p, q, "error", error=type(exc).__name__)
                return []
        return []
