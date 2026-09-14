"""Conservative itinerary identities, independent of prices and seller tokens."""

import hashlib
import json
import re
from datetime import datetime


def segment(origin, destination, departure, arrival, carrier, number):
    # Compare local airport times; never guess an offset or a flight number.
    def local(value):
        if not isinstance(value, str) or "T" not in value:
            raise ValueError("Missing departure or arrival time")
        return (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            .replace(tzinfo=None)
            .isoformat(timespec="minutes")
        )

    carrier = str(carrier).strip().upper()
    number = re.sub(r"\s+", "", str(number or "")).upper()
    if number.startswith(carrier):
        number = number[len(carrier) :]
    if not re.fullmatch(r"[A-Z0-9]{2,3}", carrier) or not re.fullmatch(
        r"\d+[A-Z]?", number
    ):
        raise ValueError("Missing flight identity")
    number = number.lstrip("0") or "0"
    if not re.fullmatch(r"[A-Z]{3}", origin) or not re.fullmatch(
        r"[A-Z]{3}", destination
    ):
        raise ValueError("Missing airport")
    return (origin, destination, local(departure), local(arrival), carrier, number)


def canonical_trip(o):
    """Only complete, connected outbound AND inbound itineraries can cross sellers."""
    raw = o.raw
    if not raw.get("_complete_trip"):
        return None
    try:
        if o.provider == "flightfinder":
            legs = [
                [
                    segment(
                        s["origin"],
                        s["destination"],
                        s["departure_time"],
                        s["arrival_time"],
                        s["carrier"],
                        s["flight_number"],
                    )
                    for s in raw[k]["segments"]
                ]
                for k in ("outbound", "inbound")
            ]
        elif o.provider == "kiwi":
            legs = [
                [
                    segment(
                        s["flyFrom"],
                        s["flyTo"],
                        s["local_departure"],
                        s["local_arrival"],
                        s["airline"],
                        s["flight_no"],
                    )
                    for s in raw["route"]
                    if s["return"] == direction
                ]
                for direction in (0, 1)
            ]
        elif o.provider == "amadeus":
            legs = [
                [
                    segment(
                        s["departure"]["iataCode"],
                        s["arrival"]["iataCode"],
                        s["departure"]["at"],
                        s["arrival"]["at"],
                        s["carrierCode"],
                        s["number"],
                    )
                    for s in leg["segments"]
                ]
                for leg in raw["itineraries"]
            ]
        else:
            return None
        if len(legs) != 2 or not all(legs):
            return None
        for leg, start, end, day in zip(
            legs,
            (o.origin, o.destination),
            (o.destination, o.origin),
            (o.departure_date, o.return_date),
        ):
            if leg[0][0] != start or leg[-1][1] != end or leg[0][2][:10] != str(day):
                return None
            if any(a[1] != b[0] for a, b in zip(leg, leg[1:])):
                return None
        return legs
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def fingerprint(o):
    raw = o.raw
    trip = canonical_trip(o)
    context = [
        raw.get("_environment", "production"),
        o.origin,
        o.destination,
        str(o.departure_date),
        str(o.return_date),
        o.currency,
    ]
    if trip:
        key = ["trip-v1", *context, trip]
    else:
        # Keep incomplete discoveries separate from complete round trips.
        itinerary = {
            k: raw[k]
            for k in ("flights", "route", "itineraries", "outbound", "inbound", "legs")
            if raw.get(k)
        }

        def stable(value):
            if isinstance(value, dict):
                return {
                    k: stable(v)
                    for k, v in value.items()
                    if not any(
                        x in k.lower()
                        for x in ("price", "fare", "token", "booking", "cost")
                    )
                    and k.lower() not in ("id", "deep_link")
                }
            if isinstance(value, list):
                return [stable(v) for v in value]
            return value

        # Chromium and HTTP use exactly the same Google parser and query contract.
        provider = (
            "fast_flights"
            if o.provider == "google_browser" and itinerary
            else o.provider
        )
        identity = (
            stable(itinerary) if itinerary else (o.provider_offer_id or str(o.price))
        )
        key = [
            provider,
            *context,
            sorted(o.airlines),
            o.stops,
            o.duration_minutes,
            bool(raw.get("_complete_trip")),
            raw.get("_quality"),
            identity,
        ]
    return hashlib.sha256(
        json.dumps(key, sort_keys=True, default=str).encode()
    ).hexdigest()
