from datetime import date


def test_previous_month_helper():
    from app.commission.routes import _previous_month
    # July 2026 -> June 2026
    assert _previous_month(date(2026, 7, 15)) == ("June 2026", "2026-06")
    # January -> previous December of prior year
    assert _previous_month(date(2026, 1, 3)) == ("December 2025", "2025-12")
