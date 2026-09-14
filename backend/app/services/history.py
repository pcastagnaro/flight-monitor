"""Historical comparisons use one minimum per UTC day, excluding the current day."""
from datetime import timedelta
from statistics import median

from app.services.resilience import utc


def history_indicator(offer, snapshots):
    observed = utc(offer.last_seen_at)
    daily = {}
    for snapshot in snapshots:
        checked = utc(snapshot.checked_at)
        if (snapshot.currency != offer.currency or snapshot.price <= 0
                or not observed - timedelta(days=30) <= checked <= observed
                or checked.date() == observed.date()):
            continue
        day = checked.date()
        daily[day] = min(daily.get(day, float("inf")), float(snapshot.price))
    result = {"level": "insufficient", "trend": "insufficient", "days": len(daily),
              "median_price": None, "vs_median_percent": None,
              "change_percent": None, "previous_date": None}
    price = float(offer.best_price)
    if daily:
        previous = max(daily)
        change = (price / daily[previous] - 1) * 100
        result.update(change_percent=round(change, 1), previous_date=previous.isoformat(),
                      trend="up" if change >= 2 else "down" if change <= -2 else "stable")
    if len(daily) >= 3:
        typical = median(daily.values())
        difference = (price / typical - 1) * 100
        result.update(median_price=round(typical, 2), vs_median_percent=round(difference, 1),
                      level="low" if difference <= -10 else "high" if difference >= 10 else "typical")
    return result
