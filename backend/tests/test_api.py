import unittest
from datetime import date, timedelta, datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db import Base, get_db
from app.models import SearchRun, Offer, PriceSnapshot


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)

        def session():
            with Session(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = session
        self.addCleanup(self.engine.dispose)
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        d = date.today() + timedelta(days=20)
        r = d + timedelta(days=10)
        self.body = {
            "name": "API test",
            "origin": "BCN",
            "destinations": ["EZE"],
            "departure_from": str(d),
            "departure_to": str(d),
            "return_from": str(r),
            "return_to": str(r),
            "require_complete_trip": True,
            "active": False,
        }

    def test_create_preview_and_pause(self):
        self.assertEqual(
            self.client.post("/api/searches/preview", json=self.body).json()[
                "planned_combinations"
            ],
            1,
        )
        response = self.client.post("/api/searches", json=self.body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["require_complete_trip"])
        id = response.json()["id"]
        self.assertTrue(
            self.client.patch(f"/api/searches/{id}/active?active=true").json()["active"]
        )
        self.assertEqual(self.client.get("/api/searches").json()[0]["name"], "API test")

    def test_bad_filter_values_rejected(self):
        for query in [
            "max_price=nan",
            "max_price=-1",
            "max_stops=8",
            "destination=Paris",
        ]:
            with self.subTest(query=query):
                self.assertEqual(
                    self.client.get("/api/searches/1/results?" + query).status_code, 422
                )

    def test_missing_and_invalid_searches(self):
        self.assertEqual(self.client.post("/api/searches/999/run").status_code, 404)
        self.assertEqual(
            self.client.post(
                "/api/searches", json=self.body | {"provider_names": ["random"]}
            ).status_code,
            422,
        )
        self.assertEqual(self.client.get("/api/offers/999/history").status_code, 404)

    def test_runs_same_timestamp_show_newest_first(self):
        id = self.client.post("/api/searches", json=self.body).json()["id"]
        with Session(self.engine) as db:
            timestamp = datetime.now(timezone.utc).replace(microsecond=0)
            db.add_all(
                [
                    SearchRun(
                        search_id=id,
                        started_at=timestamp,
                        status="ok",
                        details={"order": i},
                    )
                    for i in (1, 2)
                ]
            )
            db.commit()
        runs = self.client.get(f"/api/searches/{id}/runs").json()
        self.assertEqual([r["details"]["order"] for r in runs], [2, 1])

    def test_offer_sorting_and_filters_before_pagination(self):
        search_id = self.client.post("/api/searches", json=self.body).json()["id"]
        with Session(self.engine) as db:
            for i, (price, duration) in enumerate([(300, None), (100, 120), (200, 60)]):
                offer = Offer(
                    search_id=search_id,
                    fingerprint=str(i),
                    origin="BCN",
                    destination="EZE",
                    departure_date=date.today(),
                    return_date=date.today(),
                    best_price=price,
                    duration_minutes=duration,
                    stops=i,
                    airlines=["IB"],
                )
                db.add(offer)
                db.flush()
                db.add(
                    PriceSnapshot(
                        offer_id=offer.id,
                        provider="amadeus" if i == 1 else "kiwi",
                        price=price,
                        currency="EUR",
                        raw={},
                    )
                )
            db.commit()
        url = f"/api/searches/{search_id}/results?"

        def prices(query):
            response = self.client.get(url + query)
            self.assertEqual(response.status_code, 200, response.text)
            return [r["price"] for r in response.json()]

        self.assertEqual(prices("sort=price&direction=desc&limit=1&offset=1"), [200])
        self.assertEqual(prices("sort=duration&direction=desc"), [100, 200, 300])
        self.assertEqual(prices("sort=duration&direction=asc"), [200, 100, 300])
        self.assertEqual(prices("min_price=150&max_duration=90&limit=1"), [200])
        self.assertEqual(prices("provider=amadeus"), [100])
        self.assertEqual(
            self.client.get(url + "min_price=500&max_price=100").status_code, 400
        )
        self.assertEqual(self.client.get(url + "direction=invalid").status_code, 400)
