import random
from datetime import UTC, date, datetime, time, timedelta

from pages.schedule import IST, pick_slot, skipped_day


def at(day, h, m=0): return datetime(2026, 11, day, h, m, tzinfo=IST)


def test_slot_is_inside_the_ist_window_and_after_now():
    now = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)          # 06:30 IST
    for seed in range(50):
        slot = pick_slot("billikalesh", now, [], (9, 23), 1, random.Random(seed))
        assert 9 <= slot.astimezone(IST).hour < 23 and slot >= now + timedelta(minutes=10)


def test_three_hours_apart_and_daily_target():
    taken = [at(2, 12)]
    two = pick_slot("x", at(2, 8), taken, (9, 23), 2, random.Random(1))
    assert abs(two - taken[0]) >= timedelta(hours=3)
    one = pick_slot("x", at(2, 8), taken, (9, 23), 1, random.Random(1))
    assert one.astimezone(IST).date() > date(2026, 11, 2)


def test_skipped_days_are_occasional_differ_by_page_and_get_no_post():
    days = [date(2026, 11, 1) + timedelta(n) for n in range(90)]
    a = {d for d in days if skipped_day("podcastbawaal", d)}
    assert 4 <= len(a) <= 20 and a != {d for d in days if skipped_day("billikalesh", d)}
    first = min(a)
    slot = pick_slot("podcastbawaal", datetime.combine(first, time(0), IST), [], (9, 23), 1, random.Random(3))
    assert slot.astimezone(IST).date() != first
