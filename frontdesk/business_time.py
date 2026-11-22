"""Pure business-time calculations. Callers supply database holidays and policies."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Kolkata")


def local(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    return value.astimezone(ZONE)


class CalendarRangeError(ValueError):
    """Holiday seeds must be extended before calculating beyond their range."""


@dataclass(frozen=True)
class Calendar:
    holidays: frozenset[date]
    opens: time = time(9, 30)
    closes: time = time(18, 30)

    def check_range(self, day: date) -> None:
        if not self.holidays or day > max(self.holidays):
            last = max(self.holidays).isoformat() if self.holidays else "none"
            raise CalendarRangeError(f"Holiday calendar not seeded for {day}; last seeded holiday: {last}. Extend holiday seeds.")

    def working(self, day: date) -> bool:
        self.check_range(day)
        return day.weekday() < 5 and day not in self.holidays

    def boundary(self, day: date, clock: time) -> datetime:
        self.check_range(day)
        return datetime.combine(day, clock, ZONE)

    def normalize(self, value: datetime) -> datetime:
        value = local(value)
        while not self.working(value.date()) or value.time() >= self.closes:
            value = self.boundary(value.date() + timedelta(days=1), self.opens)
        return max(value, self.boundary(value.date(), self.opens))

    def start(self, arrival: datetime) -> datetime:
        """An arrival inside the working window starts immediately."""
        return self.normalize(arrival)

    def add(self, value: datetime, minutes: float) -> datetime:
        if not isfinite(minutes) or minutes < 0:
            raise ValueError("Duration cannot be negative")
        cursor = local(value)
        self.check_range(cursor.date())
        remaining = timedelta(minutes=minutes)
        while remaining > timedelta(0):
            cursor = self.normalize(cursor)
            end = self.boundary(cursor.date(), self.closes)
            available = end - cursor
            if remaining <= available:
                return cursor + remaining
            remaining -= available
            cursor = self.normalize(end)
        return cursor

    def minutes(self, start: datetime, end: datetime) -> float:
        start, end = local(start), local(end)
        self.check_range(start.date())
        self.check_range(end.date())
        total = timedelta(0)
        day = start.date()
        # Inspect only dates inside the requested interval. Normalizing a closed
        # end date could unnecessarily walk into an unseeded future opening.
        while day <= end.date():
            if self.working(day):
                begin = max(start, self.boundary(day, self.opens))
                stop = min(end, self.boundary(day, self.closes))
                if begin < stop:
                    total += stop - begin
            day += timedelta(days=1)
        return total.total_seconds() / 60



@dataclass(frozen=True)
class Policy:
    first_reply_minutes: int
    resolve_minutes: int | None  # None means end of the initial working day.

    def __post_init__(self):
        if self.first_reply_minutes <= 0 or (self.resolve_minutes is not None and self.resolve_minutes <= 0):
            raise ValueError("SLA targets must be positive")


@dataclass(frozen=True)
class Pause:
    paused_at: datetime
    resumed_at: datetime | None = None


def deadlines(calendar: Calendar, start: datetime, policy: Policy,
              pauses: list[Pause] | tuple[Pause, ...] = (),
              now: datetime | None = None) -> tuple[datetime, datetime]:
    """Recalculate from original start; public first reply is satisfied separately.

    Open pauses project the resolution deadline as of the supplied clock. Pauses
    that start after a deadline cannot retroactively erase an existing breach.
    """
    start = local(start)
    if now is not None:
        now = local(now)
    first = calendar.add(start, policy.first_reply_minutes)
    remaining: float = float(policy.resolve_minutes) if policy.resolve_minutes is not None else calendar.minutes(start, calendar.boundary(start.date(), calendar.closes))
    cursor = start
    previous_end = None
    intervals: list[tuple[datetime, datetime, bool]] = []
    for pause in sorted(pauses, key=lambda p: local(p.paused_at)):
        begin = local(pause.paused_at)
        if pause.resumed_at is None and now is None:
            raise ValueError("An open pause requires an explicit clock")
        end_value = pause.resumed_at if pause.resumed_at is not None else now
        assert end_value is not None
        end = local(end_value)
        if end < begin or (previous_end is not None and begin < previous_end):
            raise ValueError("Invalid or overlapping pause intervals")
        if intervals and intervals[-1][2]:
            raise ValueError("An open pause must be last")
        intervals.append((begin, end, pause.resumed_at is None))
        previous_end = end
    for begin, end, _ in intervals:
        if end <= start:
            continue
        begin = max(begin, start)
        elapsed = calendar.minutes(cursor, begin)
        if elapsed >= remaining:
            return first, calendar.add(cursor, remaining)
        remaining -= elapsed
        cursor = end
    return first, calendar.add(cursor, remaining)


def can_reopen(calendar: Calendar, resolved_at: datetime, now: datetime) -> bool:
    resolved_at, now = local(resolved_at), local(now)
    return resolved_at <= now and calendar.minutes(resolved_at, now) <= 5 * 9 * 60


def should_auto_close(calendar: Calendar, waiting_since: datetime, now: datetime) -> bool:
    return local(now) >= calendar.add(waiting_since, 5 * 9 * 60)


@dataclass(frozen=True)
class ReopenPlan:
    action: str
    cycle_start: datetime
    resolution_due: datetime


def plan_reopen(calendar: Calendar, resolved_at: datetime, now: datetime, policy: Policy) -> ReopenPlan:
    """Keep prior cycle data intact; describe a fresh cycle or linked ticket."""
    start = calendar.start(now)
    return ReopenPlan(
        action="reopen" if can_reopen(calendar, resolved_at, now) else "linked_new_ticket",
        cycle_start=start,
        resolution_due=deadlines(calendar, start, policy)[1],
    )
