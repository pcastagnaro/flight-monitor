import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch
import httpx
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from pydantic import ValidationError
from app.db import Base
from app.models import (
    Search,
    SearchRun,
    PriceSnapshot,
    ProviderState,
    Offer,
)
from app.schemas import SearchCreate
from app.providers.base import Query, ProviderOffer
from app.services.planner import plan
from app.services.resilience import Engine, valid, utc
from app.services.orchestrator import run_search, SearchBusy, _fp
from app.api.routes import results

TODAY = date.today()
D = TODAY + timedelta(days=30)
R = D + timedelta(days=14)


def search_data(**kwargs):
    return dict(
        name="Test",
        origin="BCN",
        destinations=["EZE"],
        departure_from=D,
        departure_to=D,
        return_from=R,
        return_to=R,
        **kwargs,
    )


def make_offer(name, q, **kwargs):
    defaults = dict(
        provider=name,
        provider_offer_id="flight-123",
        origin=q.origin,
        destination=q.destination,
        departure_date=q.departure_date,
        return_date=q.return_date,
        price=850,
        currency=q.currency,
        airlines=["IB"],
        stops=1,
        duration_minutes=900,
        raw={"flights": [{"flight_number": "123", "departure": str(q.departure_date)}]},
    )
    defaults.update(kwargs)
    return ProviderOffer(**defaults)


class Fake:
    enabled = True

    def __init__(self, name="serpapi", response=None):
        self.name = name
        self.response = response
        self.calls = 0

    async def search(self, q):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return (
            deepcopy(self.response)
            if self.response is not None
            else [make_offer(self.name, q)]
        )


def http_error(status, headers=None):
    response = httpx.Response(
        status,
        headers=headers,
        request=httpx.Request("GET", "https://example.test/?api_key=secret-value"),
    )
    return httpx.HTTPStatusError(
        "secret-value", request=response.request, response=response
    )


class SchemaPlannerTests(unittest.TestCase):
    def test_validation_and_normalization(self):
        data = search_data()
        data.update(origin=" bcn ", destinations=["eze", "EZE"])
        self.assertEqual(SearchCreate(**data).destinations, ["EZE"])
        for change in [
            {"departure_to": D - timedelta(days=1)},
            {"destinations": ["Paris"]},
            {"return_to": D},
            {"currency": "ZZZ"},
            {"provider_names": ["unknown"]},
            {"max_price": float("nan")},
            {"adults": 0},
            {"max_combinations": 1000},
            {"target_price": 900, "max_price": 800},
            {"min_nights": 20, "max_nights": 10},
        ]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                SearchCreate(**(search_data() | change))

    def test_planner_bounded_diverse_valid(self):
        s = SearchCreate(
            **(
                search_data()
                | dict(
                    destinations=["EZE", "AEP"],
                    departure_to=D + timedelta(days=6),
                    return_to=R + timedelta(days=6),
                    max_combinations=8,
                )
            )
        )
        qs, total = plan(s)
        self.assertEqual(total, 98)
        self.assertEqual(len(qs), 8)
        self.assertEqual(
            len({(q.destination, q.departure_date, q.return_date) for q in qs}), 8
        )
        self.assertEqual({q.destination for q in qs}, {"EZE", "AEP"})
        self.assertEqual(qs[-1].return_date, R + timedelta(days=6))

    def test_past_dates_do_not_consume_calls(self):
        s = SearchCreate(
            **(
                search_data()
                | dict(
                    departure_from=TODAY - timedelta(days=2),
                    departure_to=TODAY - timedelta(days=1),
                )
            )
        )
        self.assertEqual(plan(s), ([], 0))


class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "PROVIDER_MAX_CALLS_PER_RUN": "10",
                "PROVIDER_MONTHLY_CALL_LIMIT": "500",
                "PROVIDER_TIMEOUT_SECONDS": "2",
                "SEARCH_TIMEOUT_SECONDS": "30",
                "CACHE_TTL_SECONDS": "900",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.sql = create_engine("sqlite://")
        Base.metadata.create_all(self.sql)
        self.db = Session(self.sql, autoflush=False, expire_on_commit=False)
        self.addCleanup(self.sql.dispose)
        self.addCleanup(self.db.close)
        self.s = Search(**SearchCreate(**search_data()).model_dump())
        self.db.add(self.s)
        self.db.commit()
        self.q = Query("BCN", "EZE", D, R)

    async def test_waterfall_on_empty_error_and_filters(self):
        a = Fake("amadeus", [])
        b = Fake("kiwi", http_error(503))
        c = Fake("serpapi")
        engine = Engine(self.db, self.s, [a, b, c])
        rows = await engine.query(self.q)
        self.assertEqual([r.provider for r in rows], ["serpapi"])
        self.assertEqual((a.calls, b.calls, c.calls), (1, 2, 1))
        self.assertNotIn("secret-value", str(engine.trace))
        self.assertFalse(rows[0].live)

    async def test_complete_trip_filter_keeps_searching(self):
        self.s.require_complete_trip = True
        a = Fake("amadeus", [make_offer("amadeus", self.q)])
        b = Fake("kiwi", [make_offer("kiwi", self.q, raw={"_complete_trip": True})])
        rows = await Engine(self.db, self.s, [a, b]).query(self.q)
        self.assertEqual([r.provider for r in rows], ["kiwi"])

    async def test_price_filter_does_not_stop_failover(self):
        self.s.max_price = 900
        a = Fake("amadeus", [make_offer("amadeus", self.q, price=1000)])
        b = Fake("serpapi")
        rows = await Engine(self.db, self.s, [a, b]).query(self.q)
        self.assertEqual([r.provider for r in rows], ["serpapi"])
        self.assertEqual(b.calls, 1)

    async def test_references_and_test_fares_do_not_stop_next_tier(self):
        a = Fake("travelpayouts")
        b = Fake(
            "amadeus", [make_offer("amadeus", self.q, raw={"_environment": "test"})]
        )
        c = Fake("serpapi")
        self.assertEqual(len(await Engine(self.db, self.s, [a, b, c]).query(self.q)), 3)
        self.assertEqual(c.calls, 1)

    async def test_exhaustive_and_waterfall(self):
        a, b = Fake("amadeus"), Fake("serpapi")
        await Engine(self.db, self.s, [a, b]).query(self.q)
        self.assertEqual(b.calls, 0)
        self.s.strategy = "exhaustive"
        rows = await Engine(self.db, self.s, [a, b]).query(self.q)
        self.assertEqual(len(rows), 2)

    async def test_all_cache_checked_before_any_network(self):
        paid = Fake("amadeus")
        cached = Fake("serpapi")
        await Engine(self.db, self.s, [cached]).query(self.q)
        rows = await Engine(self.db, self.s, [paid, cached]).query(self.q)
        self.assertEqual(paid.calls, 0)
        self.assertEqual(cached.calls, 1)
        self.assertTrue(rows[0].raw["_cached"])

    async def test_429_persistent_circuit_and_retry_after(self):
        a = Fake(response=http_error(429, {"Retry-After": "900"}))
        engine = Engine(self.db, self.s, [a])
        await engine.query(self.q)
        second = Engine(self.db, self.s, [a])
        await second.query(replace(self.q, departure_date=D + timedelta(days=1)))
        self.assertEqual(a.calls, 1)
        state = self.db.get(ProviderState, "serpapi")
        self.assertGreater(
            (utc(state.blocked_until) - datetime.now(timezone.utc)).total_seconds(), 890
        )
        self.assertEqual(second.trace[0]["status"], "circuit_open")

    async def test_401_no_retries(self):
        a = Fake(response=http_error(401))
        await Engine(self.db, self.s, [a]).query(self.q)
        self.assertEqual(a.calls, 1)

    async def test_monthly_budget_persisted_and_resets_next_month(self):
        a = Fake()
        with patch.dict(os.environ, {"SERPAPI_MONTHLY_CALL_LIMIT": "1"}):
            await Engine(self.db, self.s, [a]).query(self.q)
            await Engine(self.db, self.s, [a]).query(
                replace(self.q, departure_date=D + timedelta(days=1))
            )
            self.assertEqual(a.calls, 1)
            state = self.db.get(ProviderState, "serpapi")
            state.month = "2000-01"
            self.db.commit()
            await Engine(self.db, self.s, [a]).query(
                replace(self.q, departure_date=D + timedelta(days=2))
            )
            self.assertEqual(a.calls, 2)

    async def test_run_budget_includes_retries(self):
        self.s.max_provider_calls = 1
        a = Fake("amadeus", http_error(500))
        b = Fake("serpapi")
        engine = Engine(self.db, self.s, [a, b])
        await engine.query(self.q)
        self.assertEqual((a.calls, b.calls, engine.calls), (1, 0, 1))

    async def test_timeout_cancels_underlying_operation(self):
        stopped = asyncio.Event()

        class Slow(Fake):
            async def search(self, q):
                try:
                    await asyncio.sleep(10)
                finally:
                    stopped.set()

        a = Slow()
        engine = Engine(self.db, self.s, [a])
        engine.deadline = __import__("time").monotonic() + 0.02
        self.assertEqual(await engine.query(self.q), [])
        self.assertTrue(stopped.is_set())

    async def test_three_parse_failures_open_circuit(self):
        a = Fake(response=ValueError("bad parser"))
        for i in range(4):
            await Engine(self.db, self.s, [a]).query(
                replace(self.q, departure_date=D + timedelta(days=i))
            )
        self.assertEqual(a.calls, 3)

    async def test_unknown_fields_currency_and_unsafe_links(self):
        rows = [
            make_offer("serpapi", self.q, price=float("inf")),
            make_offer("serpapi", self.q, currency="USD"),
            make_offer("serpapi", self.q, stops=None),
            make_offer("serpapi", self.q, stops=-1),
            make_offer("serpapi", self.q, booking_url="javascript:alert(1)"),
        ]
        accepted = valid(rows, self.q, self.s)
        self.assertEqual(len(accepted), 1)
        self.assertIsNone(accepted[0].booking_url)

    async def test_capabilities_skip_without_spending(self):
        a = Fake("flightpowers")
        self.q.adults = 2
        engine = Engine(self.db, self.s, [a])
        await engine.query(self.q)
        self.assertEqual(a.calls, 0)
        self.assertEqual(engine.trace[0]["status"], "unsupported")

    async def test_run_caching_keeps_timestamp_history_and_coverage(self):
        a = Fake()
        with patch("app.services.orchestrator.real_providers", return_value=[a]):
            first = await run_search(self.db, self.s)
            self.assertEqual(first.details["total_combinations"], 1)
            observed = self.db.scalar(select(Offer)).last_seen_at
            count = self.db.scalar(select(func.count()).select_from(PriceSnapshot))
            second = await run_search(self.db, self.s)
        self.assertEqual(second.details["provider_calls"], 0)
        self.assertEqual(second.details["omitted_combinations"], 0)
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(PriceSnapshot)), count
        )
        self.assertEqual(self.db.scalar(select(Offer)).last_seen_at, observed)

    async def test_failures_or_exclusions_never_create_demo(self):
        for excluded in (False, True):
            self.s.provider_names = ["amadeus"] if excluded else []
            with patch(
                "app.services.orchestrator.real_providers",
                return_value=[Fake(response=http_error(401))],
            ):
                run = await run_search(self.db, self.s)
            self.assertEqual(run.result_count, 0)
            self.assertEqual(run.details["mode"], "real")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Offer)), 0)

    async def test_lock_rejects_concurrent_search_and_releases(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        class Slow(Fake):
            async def search(self, q):
                entered.set()
                await release.wait()
                return []

        with patch("app.services.orchestrator.real_providers", return_value=[Slow()]):
            task = asyncio.create_task(run_search(self.db, self.s))
            await entered.wait()
            try:
                with self.assertRaises(SearchBusy):
                    await run_search(self.db, self.s)
            finally:
                release.set()
            await task
            await run_search(self.db, self.s)

    async def test_interrupted_run_recovers(self):
        old = SearchRun(search_id=self.s.id, status="running", details={})
        self.db.add(old)
        self.db.commit()
        with patch("app.services.orchestrator.real_providers", return_value=[]):
            await run_search(self.db, self.s)
        self.assertEqual(old.status, "failed")
        self.assertEqual(old.details["error"], "interrupted")

    async def test_amadeus_test_and_production_never_share_identity(self):
        a = make_offer(
            "amadeus", self.q, raw={"_environment": "test", "itineraries": []}
        )
        b = replace(a, raw={"_environment": "production", "itineraries": []})
        self.assertNotEqual(_fp(a), _fp(b))
        fake = Fake("amadeus", [a])
        with patch("app.services.orchestrator.real_providers", return_value=[fake]):
            await run_search(self.db, self.s)
        self.assertEqual(results(self.s.id, "real", self.db), [])
        self.assertEqual(len(results(self.s.id, "demo", self.db)), 1)

    async def test_fingerprint_ignores_price_but_keeps_flight_number(self):
        a = make_offer("serpapi", self.q)
        b = replace(a, price=700)
        c = replace(a, raw={"flights": [{"flight_number": "987", "departure": str(D)}]})
        self.assertEqual(_fp(a), _fp(b))
        self.assertNotEqual(_fp(a), _fp(c))
