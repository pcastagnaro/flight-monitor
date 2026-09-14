import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.models import Search, Offer, PriceSnapshot
from app.providers.base import ProviderOffer
from app.services.orchestrator import merge, _fp
from app.api.routes import results


def flight():
    def leg(a, b, day, number):
        return {
            "segments": [
                {
                    "origin": a,
                    "destination": b,
                    "departure_time": f"2026-11-{day}T09:00:00",
                    "arrival_time": f"2026-11-{day}T11:00:00",
                    "carrier": "IB",
                    "flight_number": number,
                }
            ]
        }

    return ProviderOffer(
        "flightfinder",
        None,
        "BCN",
        "LHR",
        date(2026, 11, 1),
        date(2026, 11, 8),
        200,
        "USD",
        ["Iberia"],
        0,
        120,
        raw={
            "_complete_trip": True,
            "outbound": leg("BCN", "LHR", "01", "0123"),
            "inbound": leg("LHR", "BCN", "08", "456"),
        },
    )


def kiwi(o):
    route = []
    for i, key in enumerate(("outbound", "inbound")):
        for s in o.raw[key]["segments"]:
            route.append(
                dict(
                    flyFrom=s["origin"],
                    flyTo=s["destination"],
                    local_departure=s["departure_time"] + ".000",
                    local_arrival=s["arrival_time"],
                    airline=s["carrier"],
                    flight_no=s["flight_number"],
                    **{"return": i},
                )
            )
    return replace(
        o,
        provider="kiwi",
        price=180,
        airlines=["IB"],
        raw={"_complete_trip": True, "route": route},
    )


class DeduplicationTests(unittest.TestCase):
    def test_cross_provider_segments_and_cheapest_duplicate(self):
        a = flight()
        b = kiwi(a)
        groups = merge([a, replace(a, price=900), b])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1].price, 180)
        self.assertEqual(sorted(x.price for x in groups[0][2]), [180, 200])
        self.assertEqual(groups[0][4], 0)  # Both use Kiwi: no independent consensus.
        self.assertEqual(
            _fp(a), _fp(replace(a, price=100, booking_url="https://example.org"))
        )

    def test_return_connection_currency_environment_remain_distinct(self):
        a = flight()
        for key, value in [
            ("flight_number", "999"),
            ("departure_time", "2026-11-08T10:00:00"),
            ("origin", "LGW"),
        ]:
            b = deepcopy(a)
            b.raw["inbound"]["segments"][0][key] = value
            self.assertNotEqual(_fp(a), _fp(b))
        self.assertNotEqual(_fp(a), _fp(replace(a, currency="EUR")))
        self.assertNotEqual(
            _fp(a), _fp(replace(a, raw={**a.raw, "_environment": "test"}))
        )
        self.assertNotEqual(
            _fp(a), _fp(replace(a, raw={**a.raw, "_complete_trip": False}))
        )

    def test_missing_identity_never_merges_across_providers(self):
        a = flight()
        a.raw["inbound"]["segments"][0]["flight_number"] = None
        self.assertNotEqual(_fp(a), _fp(kiwi(a)))

    def test_pinned_flightfinder_without_numbers_deduplicates_internally(self):
        a = flight()
        for key in ("outbound", "inbound"):
            a.raw[key]["segments"][0]["flight_number"] = None
        groups = merge([a, replace(a, price=300)])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1].price, 200)

    def test_same_google_parser_ignores_transport_and_price(self):
        a = replace(
            flight(),
            provider="fast_flights",
            raw={
                "flights": [
                    {"departure": "2026-11-01T09:00", "arrival": "2026-11-01T11:00"}
                ]
            },
        )
        self.assertEqual(_fp(a), _fp(replace(a, provider="google_browser", price=250)))

    def test_legacy_rows_group_before_pagination_without_deleting_history(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            a = flight()
            search = Search(
                name="test",
                origin="BCN",
                destinations=["LHR"],
                departure_from=a.departure_date,
                departure_to=a.departure_date,
                return_from=a.return_date,
                return_to=a.return_date,
            )
            db.add(search)
            db.flush()
            now = datetime.now(timezone.utc)
            for i, x in enumerate([replace(a, price=90), a, kiwi(a)]):
                observed = now - timedelta(days=1) if i == 0 else now
                o = Offer(
                    search_id=search.id,
                    fingerprint=str(i),
                    origin=x.origin,
                    destination=x.destination,
                    departure_date=x.departure_date,
                    return_date=x.return_date,
                    airlines=x.airlines,
                    best_price=x.price,
                    currency=x.currency,
                    stops=x.stops,
                    duration_minutes=x.duration_minutes,
                    last_seen_at=observed,
                )
                db.add(o)
                db.flush()
                db.add(
                    PriceSnapshot(
                        offer_id=o.id,
                        provider=x.provider,
                        price=x.price,
                        currency=x.currency,
                        raw=x.raw,
                        checked_at=observed,
                    )
                )
            db.commit()
            rows = results(search.id, "real", db, limit=1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["price"], 180)
            self.assertEqual(rows[0]["grouped_offers"], 3)
            self.assertEqual(rows[0]["provider_names"], ["flightfinder", "kiwi"])
            self.assertEqual(results(search.id, "real", db, offset=1), [])
            self.assertEqual(db.query(PriceSnapshot).count(), 3)
            self.assertEqual(
                results(search.id, "real", db, provider="flightfinder")[0]["price"], 200
            )
