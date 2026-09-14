import os, httpx
from .base import Query, ProviderOffer


class SerpApiProvider:
    name = "serpapi"

    def __init__(self):
        self.key = os.getenv("SERPAPI_API_KEY", "")

    @property
    def enabled(self):
        return bool(self.key)

    async def search(self, q: Query):
        params = {
            "engine": "google_flights",
            "api_key": self.key,
            "departure_id": q.origin,
            "arrival_id": q.destination,
            "outbound_date": q.departure_date.isoformat(),
            "return_date": q.return_date.isoformat(),
            "currency": q.currency,
            "hl": "en",
            "gl": "es",
            "type": 1,
            "adults": q.adults,
            "travel_class": {
                "economy": 1,
                "premium_economy": 2,
                "business": 3,
                "first": 4,
            }.get(q.cabin, 1),
            "deep_search": "true",
        }
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.get("https://serpapi.com/search.json", params=params)
            r.raise_for_status()
            data = r.json()
        if data.get("error"):
            raise ValueError("SerpApi reported an error")
        level = (data.get("price_insights") or {}).get("price_level")
        rows = (data.get("best_flights") or []) + (data.get("other_flights") or [])
        out = []
        for i, x in enumerate(rows):
            flights = x.get("flights") or []
            p = x.get("price")
            if p is None or not flights:
                continue
            airlines = list(
                dict.fromkeys(f.get("airline") for f in flights if f.get("airline"))
            )
            out.append(
                ProviderOffer(
                    self.name,
                    x.get("departure_token") or str(i),
                    q.origin,
                    q.destination,
                    q.departure_date,
                    q.return_date,
                    float(p),
                    q.currency,
                    airlines,
                    max(0, len(flights) - 1),
                    x.get("total_duration"),
                    None,
                    level,
                    False,
                    x,
                )
            )
        return out
