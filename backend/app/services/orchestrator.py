import hashlib
import json
import logging
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, text, delete
from app.models import Offer, PriceSnapshot, SearchRun, Recommendation, QueryCache
from app.providers.flightpowers import FlightPowersProvider
from app.providers.serpapi import SerpApiProvider
from app.providers.travelpayouts import TravelpayoutsProvider
from app.providers.mock import MockProvider
from app.providers.datacrawler import DataCrawlerProvider
from app.providers.extended import (
    AmadeusProvider,
    KiwiProvider,
    RyanairProvider,
    FlightFinderProvider,
    FastFlightsProvider,
    GoogleBrowserProvider,
)
from .scoring import score_offer
from .telegram import send_telegram
from .planner import plan
from .resilience import Engine, EXPERIMENTAL, FAMILIES

logger = logging.getLogger(__name__)
_local_lock = threading.Lock()


class SearchBusy(Exception):
    pass


def real_providers():
    return [
        FlightPowersProvider(),
        SerpApiProvider(),
        TravelpayoutsProvider(),
        DataCrawlerProvider(),
        AmadeusProvider(),
        KiwiProvider(),
        RyanairProvider(),
        FlightFinderProvider(),
        FastFlightsProvider(),
        GoogleBrowserProvider(),
    ]


def providers():
    return [p for p in real_providers() if p.enabled] or [MockProvider()]


def _fp(o):
    # Without complete comparable segment IDs, do not merge different extractors.
    # Keep distinct itineraries using flight/segment details where available.
    raw = o.raw
    itinerary = {
        k: raw[k]
        for k in ("flights", "route", "itineraries", "outbound", "inbound", "legs")
        if k in raw
    }

    def strip_prices(value):
        if isinstance(value, dict):
            return {
                k: strip_prices(v)
                for k, v in value.items()
                if not any(
                    x in k.lower()
                    for x in ("price", "fare", "token", "booking", "cost", "id")
                )
            }
        if isinstance(value, list):
            return [strip_prices(v) for v in value]
        return value

    identity = (
        strip_prices(itinerary) if itinerary else (o.provider_offer_id or str(o.price))
    )
    key = [
        o.provider,
        raw.get("_environment", "production"),
        o.origin,
        o.destination,
        str(o.departure_date),
        str(o.return_date),
        o.currency,
        sorted(o.airlines),
        o.stops,
        o.duration_minutes,
        identity,
    ]
    return hashlib.sha256(
        json.dumps(key, sort_keys=True, default=str).encode()
    ).hexdigest()


def merge(items):
    groups = defaultdict(list)
    for x in items:
        groups[_fp(x)].append(x)
    out = []
    for fp, xs in groups.items():
        # One observation per provider and itinerary, not duplicate best/other rows.
        xs = list({x.provider: x for x in xs}.values())
        prices = [x.price for x in xs]
        med = statistics.median(prices)
        families = {FAMILIES.get(x.provider, x.provider) for x in xs}
        live = len({FAMILIES.get(x.provider, x.provider) for x in xs if x.live})
        consensus = (
            0.0
            if len(families) < 2
            else round(100 * max(0, 1 - (max(prices) - min(prices)) / med), 1)
        )
        out.append((fp, min(xs, key=lambda x: x.price), xs, med, consensus, live))
    return out


async def run_search(db, search):
    # One global execution avoids duplicate paid work across API and worker.
    if not _local_lock.acquire(blocking=False):
        raise SearchBusy()
    connection = None
    acquired = False
    try:
        if db.bind.dialect.name == "postgresql":
            connection = db.bind.connect()
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(742916031)")
            ).scalar()
            connection.commit()
            if not acquired:
                raise SearchBusy()
        # Once this lease is held, older running rows were interrupted.
        for old in db.scalars(
            select(SearchRun).where(SearchRun.status == "running")
        ).all():
            old.status = "failed"
            old.finished_at = datetime.now(timezone.utc)
            old.details = {**(old.details or {}), "error": "interrupted"}
        db.execute(
            delete(QueryCache).where(
                QueryCache.expires_at < datetime.now(timezone.utc) - timedelta(days=1)
            )
        )
        db.commit()
        return await _run(db, search)
    finally:
        try:
            if connection is not None:
                try:
                    if acquired:
                        connection.execute(text("SELECT pg_advisory_unlock(742916031)"))
                        connection.commit()
                except BaseException:
                    connection.invalidate()
                    raise
                finally:
                    connection.close()
        finally:
            _local_lock.release()


async def _run(db, search):
    run = SearchRun(search_id=search.id, status="running", details={})
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        return await _collect(db, search, run)
    except BaseException as exc:
        db.rollback()
        run = db.get(SearchRun, run.id)
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.details = {**(run.details or {}), "error": type(exc).__name__}
        db.commit()
        raise


async def _collect(db, search, run):
    qs, total_combinations = plan(search)
    logger.info(
        "Search %s run %s started: %s planned / %s possible",
        search.id,
        run.id,
        len(qs),
        total_combinations,
    )
    configured = [p for p in real_providers() if p.enabled]
    selected = [
        p
        for p in configured
        if (search.allow_experimental or p.name not in EXPERIMENTAL)
        and (not search.provider_names or p.name in search.provider_names)
    ]
    # Never replace excluded/failed external providers with demo data.
    if not configured and not search.provider_names:
        selected = [MockProvider()]
    engine = Engine(db, search, selected)
    items = []
    completed = 0
    for q in qs:
        if time.monotonic() >= engine.deadline:
            break
        start = len(engine.trace)
        items.extend(await engine.query(q))
        if any(
            e["status"] in ("ok", "empty", "error", "cache_hit", "filtered")
            for e in engine.trace[start:]
        ):
            completed += 1
        run.details = {
            "progress": completed,
            "planned": len(qs),
            "provider_usage": engine.usage,
        }
        db.commit()
    logger.info(
        "Search %s run %s collected %s offers across %s combinations",
        search.id,
        run.id,
        len(items),
        completed,
    )
    notifications = []
    for fp, best, xs, med, consensus, live_count in merge(items):
        observed = datetime.fromisoformat(
            best.raw.get("_observed_at", datetime.now(timezone.utc).isoformat())
        )
        o = db.scalar(
            select(Offer).where(Offer.search_id == search.id, Offer.fingerprint == fp)
        )
        if not o:
            o = Offer(
                search_id=search.id,
                fingerprint=fp,
                origin=best.origin,
                destination=best.destination,
                departure_date=best.departure_date,
                return_date=best.return_date,
                airlines=best.airlines,
                stops=best.stops,
                duration_minutes=best.duration_minutes,
                currency=best.currency,
                best_price=best.price,
                median_provider_price=med,
                provider_count=len({x.provider for x in xs}),
                consensus_score=consensus,
                price_level=best.price_level,
                booking_url=best.booking_url,
                last_seen_at=observed,
            )
            db.add(o)
            db.flush()
        else:
            o.best_price = best.price
            o.median_provider_price = med
            o.provider_count = len({x.provider for x in xs})
            o.consensus_score = consensus
            o.price_level = best.price_level or o.price_level
            o.booking_url = best.booking_url or o.booking_url
            o.last_seen_at = observed
        fresh = False
        for x in xs:
            checked = datetime.fromisoformat(
                x.raw.get("_observed_at", observed.isoformat())
            )
            exists = db.scalar(
                select(PriceSnapshot.id)
                .where(
                    PriceSnapshot.offer_id == o.id,
                    PriceSnapshot.provider == x.provider,
                    PriceSnapshot.checked_at == checked,
                )
                .limit(1)
            )
            if not exists:
                db.add(
                    PriceSnapshot(
                        offer_id=o.id,
                        provider=x.provider,
                        provider_offer_id=x.provider_offer_id,
                        price=x.price,
                        currency=x.currency,
                        booking_url=x.booking_url,
                        raw=x.raw,
                        checked_at=checked,
                    )
                )
                fresh = True
        if not fresh:
            continue
        previous = db.scalar(
            select(Recommendation)
            .where(Recommendation.offer_id == o.id)
            .order_by(Recommendation.created_at.desc())
            .limit(1)
        )
        state, score_total, confidence, reasons, pct = score_offer(
            db, o, search, live_count
        )
        db.add(
            Recommendation(
                offer_id=o.id,
                state=state,
                score=score_total,
                historical_percentile=pct,
                confidence=confidence,
                reasons=reasons,
            )
        )
        if (
            best.provider != "mock"
            and state == "BUY"
            and (previous is None or previous.state != "BUY")
        ):
            notifications.append(
                f"✈️ BUY · {o.origin}→{o.destination} · {o.departure_date} / {o.return_date} · {float(o.best_price):.0f} {o.currency} · score {score_total} · confianza {confidence}%"
            )
    errors = defaultdict(list)
    for event in engine.trace:
        if event["status"] == "error":
            errors[event["provider"]].append(event["error"])
    limited = completed < len(qs) or any(
        e["status"] in ("budget_exhausted", "deadline", "circuit_open", "unsupported")
        for e in engine.trace
    )
    run.provider_count = len(selected)
    run.result_count = len(items)
    run.status = (
        ("partial" if errors or limited or total_combinations > len(qs) else "ok")
        if items
        else ("failed" if errors else "partial" if limited or not selected else "empty")
    )
    run.finished_at = datetime.now(timezone.utc)
    run.details = {
        "mode": "demo"
        if selected and all(p.name == "mock" for p in selected)
        else "real",
        "strategy": search.strategy,
        "total_combinations": total_combinations,
        "combinations": len(qs),
        "completed_combinations": completed,
        "omitted_combinations": total_combinations - completed,
        "provider_calls": engine.calls,
        "provider_usage": engine.usage,
        "provider_errors": {k: v[:3] for k, v in errors.items()},
        "trace": engine.trace,
        "providers": {
            p.name: {
                "enabled": p.enabled,
                "selected": p.name in [x.name for x in selected],
                "reason": "not_configured"
                if not p.enabled
                else "experimental_disabled"
                if p.name in EXPERIMENTAL and not search.allow_experimental
                else "excluded"
                if search.provider_names and p.name not in search.provider_names
                else "selected",
            }
            for p in real_providers()
        },
    }
    db.commit()
    # Notification failures cannot roll back successfully saved flight results.
    for message in notifications:
        try:
            await send_telegram(message)
        except Exception as exc:
            logger.warning("Notification failed: %s", type(exc).__name__)
            run.details = {**run.details, "notification_error": type(exc).__name__}
            db.commit()
    return run
