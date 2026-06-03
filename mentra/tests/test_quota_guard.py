"""Tests for DailyQuotaGuard."""

import sys
import os
import datetime
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from mentra.utils.quota_guard import DailyQuotaGuard


def test():
    print("Testing DailyQuotaGuard...")

    # 1. Basic allow/deny
    print("\n--- Test 1: Basic allow/deny ---")
    g = DailyQuotaGuard(limit=5)
    for i in range(5):
        assert g.allow(), f"Should allow request {i+1}"
    assert not g.allow(), "Should deny request 6 (over limit)"
    assert g.remaining == 0
    assert g.count == 5
    print(f"  count={g.count}, remaining={g.remaining} — PASS")

    # 2. Date reset
    print("\n--- Test 2: Date reset ---")
    g2 = DailyQuotaGuard(limit=3)
    g2.allow()
    g2.allow()
    assert g2.count == 2
    # Simulate date change
    g2._date = datetime.date.today() - datetime.timedelta(days=1)
    assert g2.allow(), "Should auto-reset on new day"
    assert g2.count == 1, "Count should be 1 after reset+allow"
    print(f"  count={g2.count} after date reset — PASS")

    # 3. Thread safety
    print("\n--- Test 3: Thread safety ---")
    g3 = DailyQuotaGuard(limit=100)
    results = []

    def worker():
        for _ in range(20):
            results.append(g3.allow())

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    allowed = sum(1 for r in results if r)
    denied = sum(1 for r in results if not r)
    assert allowed == 100, f"Expected 100 allowed, got {allowed}"
    assert denied == 100, f"Expected 100 denied, got {denied}"
    print(f"  allowed={allowed}, denied={denied} — PASS")

    # 4. Repr
    print("\n--- Test 4: Repr ---")
    g4 = DailyQuotaGuard(limit=1900)
    g4.allow()
    r = repr(g4)
    assert "1/1900" in r
    print(f"  repr={r} — PASS")

    print("\nAll DailyQuotaGuard tests PASSED!")


if __name__ == "__main__":
    test()
