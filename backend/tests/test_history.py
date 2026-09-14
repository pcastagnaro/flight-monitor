import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from app.services.history import history_indicator


class HistoryTests(unittest.TestCase):
    def indicator(self, price, points):
        now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
        offer = SimpleNamespace(best_price=price, currency="EUR", last_seen_at=now)
        snapshots = [SimpleNamespace(price=p, currency=currency,
                     checked_at=now - timedelta(days=days)) for days, p, currency in points]
        return history_indicator(offer, snapshots)

    def test_levels_and_trends(self):
        points = [(d, 100, "EUR") for d in (1, 2, 3)]
        for price, level, trend in [(80, "low", "down"), (100, "typical", "stable"), (120, "high", "up")]:
            with self.subTest(price=price):
                result = self.indicator(price, points)
                self.assertEqual((result["level"], result["trend"]), (level, trend))
                self.assertEqual(result["median_price"], 100)

    def test_excludes_current_day_old_future_and_other_currencies(self):
        result = self.indicator(100, [(0, 1, "EUR"), (31, 1, "EUR"), (-1, 1, "EUR"), (1, 1, "USD")])
        self.assertEqual(result["days"], 0)
        self.assertEqual(result["trend"], "insufficient")

    def test_daily_minimum_and_sparse_history(self):
        result = self.indicator(110, [(2, 100, "EUR"), (2, 200, "EUR"), (2, 300, "EUR")])
        self.assertEqual(result["days"], 1)
        self.assertEqual(result["level"], "insufficient")
        self.assertEqual(result["change_percent"], 10)
        self.assertEqual(result["previous_date"], "2026-09-12")
