import asyncio
from datetime import date
import os
import unittest
from unittest.mock import patch

import httpx

from app.providers.base import Query
from app.providers.datacrawler import DataCrawlerProvider


class DataCrawlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DATACRAWLER_API_KEY": "test-key", "DATACRAWLER_MAX_REQUESTS_PER_RUN": "2"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.provider = DataCrawlerProvider()
        self.query = Query("BCN", "EZE", date(2026, 11, 25), date(2027, 1, 10), adults=2)
        self.payload = {"status": True, "data": {"itineraries": {"topFlights": [
            {"price": 800, "stops": 1, "duration": {"raw": 900}, "airlines": ["Iberia"]},
            {"price": 700, "stops": 2}, {"price": "unknown", "stops": 0},
        ]}}}

    def test_normalization_and_discovery(self):
        offers = self.provider.parse(self.payload, self.query)
        self.assertEqual(len(offers), 1)
        self.assertEqual((offers[0].price, offers[0].currency, offers[0].duration_minutes), (800, "EUR", 900))
        self.assertFalse(offers[0].live)
        self.assertEqual(offers[0].airlines, ["Iberia"])

    def test_bad_response_and_empty_results(self):
        for payload in ({"status": False}, {"status": True, "data": []}):
            with self.assertRaises(ValueError):
                self.provider.parse(payload, self.query)
        self.assertEqual(self.provider.parse({"status": True, "data": {"itineraries": {"topFlights": []}}}, self.query), [])

    async def test_request_and_concurrent_limit(self):
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.headers["x-rapidapi-key"], "test-key")
            self.assertEqual(request.url.params["return_date"], "2027-01-10")
            self.assertEqual(request.url.params["adults"], "2")
            return httpx.Response(200, json=self.payload)
        client_class = httpx.AsyncClient
        with patch("app.providers.datacrawler.httpx.AsyncClient", side_effect=lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)):
            await asyncio.gather(*(self.provider.search(self.query) for _ in range(10)))
        self.assertEqual(len(requests), 2)
        self.assertEqual(self.provider.skipped, 8)

    async def test_quota_error_stops_later_calls(self):
        client_class = httpx.AsyncClient
        with patch("app.providers.datacrawler.httpx.AsyncClient", side_effect=lambda **kw: client_class(transport=httpx.MockTransport(lambda r: httpx.Response(429)), **kw)):
            with self.assertRaises(httpx.HTTPStatusError):
                await self.provider.search(self.query)
            self.assertEqual(await self.provider.search(self.query), [])
        self.assertEqual(self.provider.requests, 1)

    def test_disabled_without_key_or_with_zero_limit(self):
        with patch.dict(os.environ, {"DATACRAWLER_API_KEY": ""}):
            self.assertFalse(DataCrawlerProvider().enabled)
        with patch.dict(os.environ, {"DATACRAWLER_MAX_REQUESTS_PER_RUN": "0"}):
            self.assertFalse(DataCrawlerProvider().enabled)
