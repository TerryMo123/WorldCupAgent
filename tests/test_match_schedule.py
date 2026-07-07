from datetime import date, datetime, timezone, timedelta

from app.services.match_schedule import (
    filter_cards_by_beijing_date,
    format_kickoff_beijing,
    match_status,
    refresh_match_card,
)


def test_kickoff_display_beijing_full_datetime():
    kickoff = datetime(2026, 7, 3, 18, 0, tzinfo=timezone(timedelta(hours=-4)))
    display, _, local = format_kickoff_beijing(kickoff)
    assert display == "2026-07-04 06:00"
    assert local is not None and "+08:00" in local


def test_status_scheduled_without_score_even_after_kickoff():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    kickoff_utc = datetime(2026, 7, 3, 3, 0, tzinfo=timezone.utc)
    assert match_status(None, None, kickoff_utc, "2026-07-02", tz) == "scheduled"


def test_status_finished_with_score():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    assert match_status(2, 1, None, "2026-07-03", tz) == "finished"


def test_filter_by_beijing_date():
    cards = [
        {
            "match_id": "a",
            "date": "2026-07-03",
            "kickoff_utc": "2026-07-03T22:00:00+00:00",
            "home": {"score": None},
            "away": {"score": None},
        }
    ]
    result = filter_cards_by_beijing_date(cards, date(2026, 7, 4))
    assert len(result) == 1
    assert result[0]["kickoff_display"].startswith("2026-07-04")
    assert result[0]["status"] == "scheduled"


def test_refresh_match_card():
    card = refresh_match_card(
        {
            "date": "2026-07-03",
            "kickoff_utc": "2026-07-03T22:00:00+00:00",
            "time_raw": "18:00 UTC-4",
            "home": {"score": None},
            "away": {"score": None},
        }
    )
    assert card["kickoff_display"] == "2026-07-04 06:00"
    assert card["status"] == "scheduled"
