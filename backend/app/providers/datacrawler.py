"""DataCrawler Google Flights discovery (no automatic booking/pagination calls)."""
import math
import os

import httpx

from .base import Query, ProviderOffer


class DataCrawlerProvider:
    name = "datacrawler"
    host = "google-flights2.p.rapidapi.com"

    def __init__(self):
        self.key = os.getenv("DATACRAWLER_API_KEY", "")
        self.limit = max(0, int(os.getenv("DATACRAWLER_MAX_REQUESTS_PER_RUN", "5")))
        self.requests = 0
        self.skipped = 0
        self.blocked = False

    @property
    def enabled(self):
        return bool(self.key) and self.limit > 0

    async def search(self, q: Query):
        # Instances are shared for one run. Reserve before the first await.
        if self.blocked or self.requests >= self.limit:
            self.skipped += 1
            return []
        self.requests += 1
        params = {
            "departure_id": q.origin, "arrival_id": q.destination,
            "outbound_date": q.departure_date.isoformat(),
            "return_date": q.return_date.isoformat(),
            "adults": q.adults, "travel_class": q.cabin.upper(),
            "currency": q.currency.upper(), "language_code": "en-US",
            "country_code": "ES", "search_type": "best", "show_hidden": "0",
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.get(
                f"https://{self.host}/api/v1/searchFlights", params=params,
                headers={"x-rapidapi-host": self.host, "x-rapidapi-key": self.key},
            )
        if response.status_code in (401, 403, 429):
            self.blocked = True
        response.raise_for_status()
        return self.parse(response.json(), q)

    def parse(self, payload, q):
        if not isinstance(payload, dict) or payload.get("status") is not True:
            raise ValueError("DataCrawler reported an unsuccessful search")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("itineraries"), dict):
            raise ValueError("Unexpected DataCrawler itineraries format")
        groups = data["itineraries"]
        out = []
        for group, rows in groups.items():
            if not isinstance(rows, list):
                continue
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                price = row.get("price")
                if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
                    continue
                stops = row.get("stops")
                if not isinstance(stops, int) or isinstance(stops, bool) or stops < 0:
                    stops = None
                if q.max_stops is not None and (stops is None or stops > q.max_stops):
                    continue
                duration = row.get("duration")
                minutes = duration.get("raw") if isinstance(duration, dict) else None
                if not isinstance(minutes, int) or minutes < 0:
                    minutes = None
                airlines = row.get("airlines") or []
                if not isinstance(airlines, list):
                    airlines = []
                airlines = list(dict.fromkeys(a for a in airlines if isinstance(a, str) and a))
                out.append(ProviderOffer(
                    provider=self.name, provider_offer_id=f"{group}:{i}",
                    origin=q.origin, destination=q.destination,
                    departure_date=q.departure_date, return_date=q.return_date,
                    price=float(price), currency=q.currency, airlines=airlines,
                    stops=stops, duration_minutes=minutes,
                    # Discovery does not prove the paired return or bookable total.
                    # Keep it out of BUY eligibility until that flow is verified.
                    live=False, raw={**row, "_search_stage": "discovery"},
                ))
        return out
