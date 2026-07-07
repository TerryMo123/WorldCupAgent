from datetime import datetime, timezone

from app.utils.timezone import to_beijing_display


def test_utc_to_beijing_display():
    # 08:29:26 UTC → 16:29:26 北京时间
    assert to_beijing_display("2026-07-03T08:29:26+00:00") == "2026-07-03 16:29:26"
    assert to_beijing_display("2026-07-03T08:29:26Z") == "2026-07-03 16:29:26"

    dt = datetime(2026, 7, 3, 8, 29, 26, tzinfo=timezone.utc)
    assert to_beijing_display(dt) == "2026-07-03 16:29:26"
