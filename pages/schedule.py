import hashlib
import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def skipped_day(page: str, day: date) -> bool:
    return int(hashlib.sha256(f"{page}:{day}".encode()).hexdigest(), 16) % 9 == 0


def pick_slot(page: str, now: datetime, taken: list[datetime], window: tuple[int, int],
              daily_target: int, rng=random) -> datetime | None:
    start = now.astimezone(IST).date()
    for n in range(14):
        day = start + timedelta(n)
        if skipped_day(page, day) or sum(t.astimezone(IST).date() == day for t in taken) >= daily_target:
            continue
        opens = datetime.combine(day, time(window[0]), IST)
        for _ in range(50):
            slot = opens + timedelta(minutes=rng.randrange((window[1] - window[0]) * 60))
            if slot >= now + timedelta(minutes=10) and all(abs(slot - t) >= timedelta(hours=3) for t in taken):
                return slot.astimezone(UTC)
    return None
