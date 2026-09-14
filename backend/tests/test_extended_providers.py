import importlib.util
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch
import httpx
from app.providers.base import Query
from app.providers.extended import (
    AmadeusProvider,
    KiwiProvider,
    RyanairProvider,
    FastFlightsProvider,
    FlightFinderProvider,
    GoogleBrowserProvider,
)

Q = Query(
    "BCN", "EZE", date(2026, 11, 25), date(2027, 1, 2), adults=2, cabin="business"
)


def amadeus_data():
    def segment(origin, dest, day):
        return {
            "departure": {"iataCode": origin, "at": day + "T10:00:00"},
            "arrival": {"iataCode": dest, "at": day + "T20:00:00"},
            "carrierCode": "IB",
            "number": "123",
        }

    return {
        "data": [
            {
                "price": {"grandTotal": "1800.00", "currency": "EUR"},
                "itineraries": [
                    {
                        "duration": "PT13H20M",
                        "segments": [segment("BCN", "EZE", "2026-11-25")],
                    },
                    {
                        "duration": "PT12H",
                        "segments": [segment("EZE", "BCN", "2027-01-02")],
                    },
                ],
            }
        ]
    }


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def mock_client(self, handle):
        cls = httpx.AsyncClient
        return patch(
            "app.providers.extended.httpx.AsyncClient",
            side_effect=lambda **kw: cls(transport=httpx.MockTransport(handle), **kw),
        )

    async def test_amadeus_token_reuse_and_passenger_currency_class(self):
        requests = []

        def handle(request):
            requests.append(request)
            if request.url.path.endswith("/token"):
                return httpx.Response(
                    200, json={"access_token": "test", "expires_in": 1800}
                )
            self.assertEqual(request.url.params["adults"], "2")
            self.assertEqual(request.url.params["currencyCode"], "EUR")
            self.assertEqual(request.url.params["travelClass"], "BUSINESS")
            self.assertEqual(request.headers["Authorization"], "Bearer test")
            return httpx.Response(200, json=amadeus_data())

        p = AmadeusProvider()
        with self.mock_client(handle):
            rows = await p.search(Q)
            await p.search(Q)
        self.assertEqual(len(requests), 3)
        self.assertEqual(rows[0].price, 1800)
        self.assertEqual(rows[0].duration_minutes, 800)
        self.assertEqual(rows[0].raw["_environment"], "test")
        self.assertFalse(rows[0].live)

    def test_amadeus_missing_return_currency_or_wrong_airport_rejected(self):
        p = AmadeusProvider()
        for mutation in ["return", "currency", "airport", "date"]:
            data = amadeus_data()
            if mutation == "return":
                data["data"][0]["itineraries"].pop()
            elif mutation == "currency":
                data["data"][0]["price"]["currency"] = "USD"
            elif mutation == "airport":
                data["data"][0]["itineraries"][1]["segments"][0]["arrival"][
                    "iataCode"
                ] = "MAD"
            else:
                data["data"][0]["itineraries"][1]["segments"][0]["departure"]["at"] = (
                    "2027-01-03T10:00:00"
                )
            self.assertEqual(p.parse(data, Q), [])
        with self.assertRaises(ValueError):
            p.parse({"error": "bad"}, Q)

    async def test_kiwi_query_and_paired_return(self):
        payload = {
            "currency": "EUR",
            "data": [
                {
                    "price": 1500,
                    "airlines": ["IB"],
                    "route": [
                        {
                            "return": 0,
                            "flyFrom": "BCN",
                            "flyTo": "EZE",
                            "local_departure": "2026-11-25T12:00:00",
                        },
                        {
                            "return": 1,
                            "flyFrom": "EZE",
                            "flyTo": "BCN",
                            "local_departure": "2027-01-02T12:00:00",
                        },
                    ],
                    "duration": {"departure": 36000, "return": 40000},
                    "deep_link": "https://www.kiwi.com/deep",
                }
            ],
        }

        def handle(request):
            self.assertEqual(request.url.params["adults"], "2")
            self.assertEqual(request.url.params["selected_cabins"], "C")
            self.assertEqual(request.url.params["return_from"], "02/01/2027")
            return httpx.Response(200, json=payload)

        with self.mock_client(handle):
            rows = await KiwiProvider().search(Q)
        self.assertEqual((rows[0].price, rows[0].stops), (1500, 0))
        payload["data"][0]["route"].pop()
        self.assertEqual(KiwiProvider().parse(payload, Q), [])

    async def test_ryanair_two_fares_not_verified_total(self):
        q = deepcopy(Q)
        q.adults = 1
        q.cabin = "economy"

        def handle(request):
            day = request.url.params["outboundMonthOfDate"]
            return httpx.Response(
                200,
                json={
                    "outbound": {
                        "fares": [
                            {
                                "day": day,
                                "soldOut": False,
                                "unavailable": False,
                                "price": {"value": 60, "currencyCode": "EUR"},
                            }
                        ]
                    }
                },
            )

        with self.mock_client(handle):
            rows = await RyanairProvider().search(q)
        self.assertEqual(rows[0].price, 120)
        self.assertEqual(rows[0].raw["_quality"], "separate_tickets")
        self.assertFalse(rows[0].live)
        self.assertFalse(RyanairProvider().supports(Q))

    @unittest.skipUnless(
        importlib.util.find_spec("fast_flights"),
        "Install requirements-experimental.txt",
    )
    async def test_fast_flights_currency_and_schema_contract(self):
        p = FastFlightsProvider()
        params = p.make_query(Q).params()
        self.assertEqual(params["curr"], "EUR")
        self.assertIn("tfs", params)

        def handle(request):
            return httpx.Response(429, headers={"Retry-After": "500"})

        with self.mock_client(handle), self.assertRaises(httpx.HTTPStatusError):
            await p.search(Q)
        with self.assertRaises(Exception):
            p.parse_html("<html>consent</html>", Q)

    @unittest.skipUnless(
        importlib.util.find_spec("flightfinder"),
        "Install requirements-experimental.txt",
    )
    async def test_flightfinder_errors_preserve_status_for_circuit(self):
        p = FlightFinderProvider()
        q = deepcopy(Q)
        q.currency = "USD"
        self.assertFalse(p.supports(Q))

        def handle(request):
            import json

            data = json.loads(request.content)
            self.assertFalse(data["variables"]["filter"]["enableTrueHiddenCity"])
            self.assertEqual(data["variables"]["options"]["currency"], "usd")
            return httpx.Response(429, headers={"Retry-After": "900"})

        with (
            self.mock_client(handle),
            self.assertRaises(httpx.HTTPStatusError) as caught,
        ):
            await p.search(q)
        self.assertEqual(caught.exception.response.status_code, 429)

    @unittest.skipUnless(
        importlib.util.find_spec("playwright"), "Install requirements-browser.txt"
    )
    async def test_browser_cleanup_on_parse_failure(self):
        from unittest.mock import AsyncMock, MagicMock

        browser = AsyncMock()
        page = AsyncMock()
        browser.new_page.return_value = page
        page.url = "https://www.google.com/travel/flights"
        response = MagicMock()
        response.status = 200
        page.goto.return_value = response
        page.content.return_value = "<html>unexpected parser response</html>"
        runtime = MagicMock()
        runtime.chromium.launch = AsyncMock(return_value=browser)
        manager = AsyncMock()
        manager.__aenter__.return_value = runtime
        with (
            patch("playwright.async_api.async_playwright", return_value=manager),
            self.assertRaises(Exception),
        ):
            await GoogleBrowserProvider().search(Q)
        browser.close.assert_awaited_once()
