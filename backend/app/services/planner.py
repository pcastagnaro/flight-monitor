"""Bounded, evenly spread sampling; never silently truncate a date window."""

from datetime import date, timedelta
from app.providers.base import Query


def plan(search):
    pairs = []
    d = max(search.departure_from, date.today())
    while d <= search.departure_to:
        r = max(search.return_from, d + timedelta(days=search.min_nights))
        while r <= min(search.return_to, d + timedelta(days=search.max_nights)):
            pairs.append((d, r))
            r += timedelta(days=1)
        d += timedelta(days=1)
    # Round-robin destinations with an even spread across date pairs.
    total = len(pairs) * len(search.destinations)
    limit = min(total, search.max_combinations)
    queries = []
    for i in range(limit):
        dest = search.destinations[i % len(search.destinations)]
        count = (
            limit + len(search.destinations) - 1 - i % len(search.destinations)
        ) // len(search.destinations)
        j = i // len(search.destinations)
        index = round(j * (len(pairs) - 1) / max(1, count - 1))
        d, r = pairs[index]
        queries.append(
            Query(
                search.origin,
                dest,
                d,
                r,
                search.adults,
                search.cabin,
                search.max_stops,
                search.currency,
            )
        )
    return queries, total
