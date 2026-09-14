"""Independent adapters; unofficial sources remain opt-in and discovery-only."""

import importlib.util
import os
import re
import time
from datetime import date
import httpx
from .base import ProviderOffer


def enabled_flag(name):
    return os.getenv(name, "").lower() in ("1", "true", "yes")


def duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value or "")
    return int(match[1] or 0) * 60 + int(match[2] or 0) if match else None


def offer(name, q, price, **kwargs):
    return ProviderOffer(
        provider=name,
        provider_offer_id=None,
        origin=q.origin,
        destination=q.destination,
        departure_date=q.departure_date,
        return_date=q.return_date,
        price=float(price),
        currency=q.currency,
        live=False,
        **kwargs,
    )


class AmadeusProvider:
    name = "amadeus"

    def __init__(self):
        self.key = os.getenv("AMADEUS_CLIENT_ID", "")
        self.secret = os.getenv("AMADEUS_CLIENT_SECRET", "")
        self.production = enabled_flag("AMADEUS_PRODUCTION")
        self.url = (
            "https://api.amadeus.com"
            if self.production
            else "https://test.api.amadeus.com"
        )
        self.token, self.expires = "", 0

    @property
    def enabled(self):
        return bool(self.key and self.secret)

    async def search(self, q):
        async with httpx.AsyncClient(timeout=20) as client:
            if time.monotonic() >= self.expires:
                r = await client.post(
                    self.url + "/v1/security/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.key,
                        "client_secret": self.secret,
                    },
                )
                r.raise_for_status()
                data = r.json()
                self.token = data["access_token"]
                self.expires = time.monotonic() + max(0, int(data["expires_in"]) - 30)
            r = await client.get(
                self.url + "/v2/shopping/flight-offers",
                headers={"Authorization": f"Bearer {self.token}"},
                params={
                    "originLocationCode": q.origin,
                    "destinationLocationCode": q.destination,
                    "departureDate": str(q.departure_date),
                    "returnDate": str(q.return_date),
                    "adults": q.adults,
                    "travelClass": q.cabin.upper(),
                    "currencyCode": q.currency,
                    "max": 30,
                    "nonStop": str(q.max_stops == 0).lower(),
                },
            )
            if r.status_code == 401:
                self.expires = 0
            r.raise_for_status()
            return self.parse(r.json(), q)

    def parse(self, data, q):
        if not isinstance(data.get("data"), list):
            raise ValueError("Invalid Amadeus response")
        out = []
        for row in data["data"]:
            try:
                legs = row["itineraries"]
                if len(legs) != 2 or any(not leg.get("segments") for leg in legs):
                    continue
                a, b = [leg["segments"] for leg in legs]
                if (
                    a[0]["departure"]["iataCode"],
                    a[-1]["arrival"]["iataCode"],
                    b[0]["departure"]["iataCode"],
                    b[-1]["arrival"]["iataCode"],
                ) != (q.origin, q.destination, q.destination, q.origin):
                    continue
                if a[0]["departure"]["at"][:10] != str(q.departure_date) or b[0][
                    "departure"
                ]["at"][:10] != str(q.return_date):
                    continue
                if row["price"]["currency"] != q.currency:
                    continue
                out.append(
                    offer(
                        self.name,
                        q,
                        row["price"]["grandTotal"],
                        airlines=list(
                            dict.fromkeys(
                                s["carrierCode"]
                                for leg in legs
                                for s in leg["segments"]
                            )
                        ),
                        stops=max(len(a), len(b)) - 1,
                        duration_minutes=max(
                            duration(l.get("duration")) or 0 for l in legs
                        )
                        or None,
                        raw={
                            **row,
                            "_environment": "production" if self.production else "test",
                            "_quality": "discovery",
                            "_complete_trip": True,
                        },
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out


class KiwiProvider:
    name = "kiwi"

    def __init__(self):
        self.key = os.getenv("KIWI_API_KEY", "")

    @property
    def enabled(self):
        return bool(self.key)

    async def search(self, q):
        fmt = lambda d: d.strftime("%d/%m/%Y")
        params = dict(
            fly_from=q.origin,
            fly_to=q.destination,
            date_from=fmt(q.departure_date),
            date_to=fmt(q.departure_date),
            return_from=fmt(q.return_date),
            return_to=fmt(q.return_date),
            flight_type="round",
            adults=q.adults,
            curr=q.currency,
            selected_cabins={
                "economy": "M",
                "premium_economy": "W",
                "business": "C",
                "first": "F",
            }[q.cabin],
            limit=30,
            sort="price",
        )
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://api.tequila.kiwi.com/v2/search",
                headers={"apikey": self.key},
                params=params,
            )
            r.raise_for_status()
            return self.parse(r.json(), q)

    def parse(self, data, q):
        if (
            not isinstance(data.get("data"), list)
            or data.get("currency", q.currency) != q.currency
        ):
            raise ValueError("Invalid Kiwi response")
        out = []
        for row in data["data"]:
            try:
                a = [s for s in row["route"] if s["return"] == 0]
                b = [s for s in row["route"] if s["return"] == 1]
                if not a or not b:
                    continue
                if (
                    a[0]["flyFrom"],
                    a[-1]["flyTo"],
                    b[0]["flyFrom"],
                    b[-1]["flyTo"],
                ) != (q.origin, q.destination, q.destination, q.origin):
                    continue
                if a[0]["local_departure"][:10] != str(q.departure_date) or b[0][
                    "local_departure"
                ][:10] != str(q.return_date):
                    continue
                out.append(
                    offer(
                        self.name,
                        q,
                        row["price"],
                        airlines=row.get("airlines", []),
                        stops=max(len(a), len(b)) - 1,
                        duration_minutes=max(
                            row.get("duration", {}).get("departure", 0),
                            row.get("duration", {}).get("return", 0),
                        )
                        // 60
                        or None,
                        booking_url=row.get("deep_link"),
                        raw={**row, "_quality": "discovery", "_complete_trip": True},
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out


class RyanairProvider:
    name = "ryanair"

    def __init__(self):
        self.months = {}

    @property
    def enabled(self):
        return enabled_flag("RYANAIR_ENABLED")

    def supports(self, q):
        return q.adults == 1 and q.cabin == "economy"

    async def search(self, q):
        legs = []
        async with httpx.AsyncClient(timeout=15) as client:
            for origin, dest, day in [
                (q.origin, q.destination, q.departure_date),
                (q.destination, q.origin, q.return_date),
            ]:
                key = (origin, dest, day.strftime("%Y-%m"), q.currency)
                if key not in self.months:
                    r = await client.get(
                        f"https://www.ryanair.com/api/farfnd/v4/oneWayFares/{origin}/{dest}/cheapestPerDay",
                        params={
                            "outboundMonthOfDate": str(day),
                            "currency": q.currency,
                        },
                    )
                    r.raise_for_status()
                    self.months[key] = r.json()["outbound"]["fares"]
                rows = self.months[key]
                leg = next(
                    (
                        x
                        for x in rows
                        if x.get("day") == str(day)
                        and not x.get("soldOut")
                        and not x.get("unavailable")
                        and x.get("price")
                    ),
                    None,
                )
                if not leg or leg["price"]["currencyCode"] != q.currency:
                    return []
                legs.append(leg)
        # Two separate indicative fares, never a verified round-trip quotation.
        return [
            offer(
                self.name,
                q,
                sum(x["price"]["value"] for x in legs),
                airlines=["Ryanair"],
                stops=0,
                raw={
                    "legs": legs,
                    "_quality": "separate_tickets",
                    "_price_basis": "one_adult",
                },
            )
        ]


class FlightFinderProvider:
    name = "flightfinder"

    @property
    def enabled(self):
        return (
            enabled_flag("FLIGHTFINDER_ENABLED")
            and importlib.util.find_spec("flightfinder") is not None
        )

    def supports(self, q):
        # The pinned upstream parser hardcodes USD. Never relabel a price as EUR.
        return q.currency == "USD"

    async def search(self, q):
        from flightfinder import AsyncFlightFinder, Config

        class ManagedClient(AsyncFlightFinder):
            async def _execute_query(self, query, variables, feature_name=None):
                # Let our engine own retries, quotas and HTTP error handling.
                variables["filter"].update(
                    allowChangeInboundDestination=False,
                    allowChangeInboundSource=False,
                    enableSelfTransfer=False,
                    enableThrowAwayTicketing=False,
                    enableTrueHiddenCity=False,
                )
                response = await self.client.post(
                    self.config.api.base_url,
                    params={"featureName": feature_name} if feature_name else {},
                    json={"query": query, "variables": variables},
                )
                response.raise_for_status()
                data = response.json()
                result = (data.get("data") or {}).get("returnItineraries")
                if (
                    data.get("errors")
                    or not isinstance(result, dict)
                    or not isinstance(result.get("itineraries"), list)
                ):
                    raise ValueError("Invalid Kiwi GraphQL response")
                return data

        config = Config()
        config.api.max_retries = 1
        config.api.timeout = 15
        config.cache.enabled = False
        config.search_defaults.currency = "usd"
        async with ManagedClient(config=config) as client:
            rows = await client.search_roundtrip(
                origin=q.origin,
                destination=q.destination,
                departure_from=q.departure_date,
                departure_to=q.departure_date,
                return_from=q.return_date,
                return_to=q.return_date,
                min_days=(q.return_date - q.departure_date).days,
                max_days=(q.return_date - q.departure_date).days,
                adults=q.adults,
                cabin_class=q.cabin.upper(),
                max_stops=q.max_stops,
                limit=30,
            )
        out = []
        for row in rows:
            if (
                row.currency != "USD"
                or row.origin != q.origin
                or row.destination != q.destination
                or row.inbound.origin != q.destination
                or row.inbound.destination != q.origin
            ):
                continue
            if (
                row.outbound.departure_time.date() != q.departure_date
                or row.inbound.departure_time.date() != q.return_date
            ):
                continue
            out.append(
                offer(
                    self.name,
                    q,
                    row.price,
                    airlines=list(
                        dict.fromkeys(row.outbound.carriers + row.inbound.carriers)
                    ),
                    stops=max(row.outbound.stops, row.inbound.stops),
                    duration_minutes=max(
                        row.outbound.duration_minutes, row.inbound.duration_minutes
                    ),
                    booking_url=row.booking_url,
                    raw={
                        **row.model_dump(mode="json"),
                        "_quality": "discovery",
                        "_complete_trip": True,
                    },
                )
            )
        return out


class FastFlightsProvider:
    name = "fast_flights"

    @property
    def enabled(self):
        return (
            enabled_flag("FAST_FLIGHTS_ENABLED")
            and importlib.util.find_spec("fast_flights") is not None
        )

    def make_query(self, q):
        from fast_flights import FlightQuery, Passengers, create_query

        return create_query(
            flights=[
                FlightQuery(
                    date=str(q.departure_date),
                    from_airport=q.origin,
                    to_airport=q.destination,
                    max_stops=q.max_stops,
                ),
                FlightQuery(
                    date=str(q.return_date),
                    from_airport=q.destination,
                    to_airport=q.origin,
                    max_stops=q.max_stops,
                ),
            ],
            trip="round-trip",
            seat=q.cabin.replace("_", "-"),
            passengers=Passengers(adults=q.adults),
            currency=q.currency,
            language="en",
        )

    async def search(self, q):
        query = self.make_query(q)
        # Use cancellable HTTP, not the library's blocking client or a browser subprocess.
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(
                "https://www.google.com/travel/flights", params=query.params()
            )
            r.raise_for_status()
        if r.url.host not in (
            "www.google.com",
            "google.com",
        ) or "consent.google" in str(r.url):
            raise ValueError("Consent or unexpected redirect")
        return self.parse_html(r.text, q)

    def parse_html(self, html, q):
        from fast_flights.parser import parse

        rows = parse(html)
        out = []
        from dataclasses import asdict

        for row in rows:
            if not row.flights or row.price is None:
                continue
            first, last = row.flights[0], row.flights[-1]
            if (
                first.from_airport.code != q.origin
                or last.to_airport.code != q.destination
                or date(*first.departure.date) != q.departure_date
            ):
                continue
            out.append(
                offer(
                    self.name,
                    q,
                    row.price,
                    airlines=row.airlines,
                    stops=len(row.flights) - 1,
                    raw={
                        **asdict(row),
                        "_quality": "discovery",
                        "_return_unverified": True,
                    },
                )
            )
        return out


class GoogleBrowserProvider(FastFlightsProvider):
    """Last tier: local Chromium, using the same deterministic data parser."""

    name = "google_browser"

    @property
    def enabled(self):
        return (
            enabled_flag("GOOGLE_BROWSER_ENABLED")
            and importlib.util.find_spec("playwright") is not None
            and importlib.util.find_spec("fast_flights") is not None
        )

    async def search(self, q):
        from playwright.async_api import async_playwright
        from urllib.parse import urlencode

        query = self.make_query(q)
        async with async_playwright() as runtime:
            browser = await runtime.chromium.launch(headless=True)
            try:
                page = await browser.new_page(locale="en-US")
                response = await page.goto(
                    "https://www.google.com/travel/flights?"
                    + urlencode(query.params()),
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                if response is not None and response.status >= 400:
                    response_error = httpx.Response(
                        response.status,
                        headers=await response.all_headers(),
                        request=httpx.Request(
                            "GET", "https://www.google.com/travel/flights"
                        ),
                    )
                    response_error.raise_for_status()
                if "consent.google" in page.url:
                    # A fresh, anonymous browser rejects optional cookies; it never solves challenges.
                    await page.get_by_role(
                        "button", name="Reject all", exact=True
                    ).click(timeout=5000)
                    await page.wait_for_url(
                        "https://www.google.com/travel/flights**", timeout=10000
                    )
                if "consent.google" in page.url or "/sorry/" in page.url:
                    raise ValueError("Consent or challenge page")
                await page.wait_for_selector(
                    "script.ds\\:1", state="attached", timeout=10000
                )
                return self.parse_html(await page.content(), q)
            finally:
                await browser.close()
