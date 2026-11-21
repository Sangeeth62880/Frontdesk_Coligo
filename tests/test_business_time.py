from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from frontdesk.business_time import Calendar, Pause, Policy, deadlines, can_reopen, should_auto_close

TZ = ZoneInfo("Asia/Kolkata")

def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=TZ)

@pytest.fixture
def calendar():
    return Calendar(frozenset({date(2026, 12, 25), date(2027, 12, 25)}))

@pytest.mark.parametrize("arrival, expected", [
    ("2026-11-20T18:00", "2026-11-20T18:00"),
    ("2026-11-21T11:00", "2026-11-23T09:30"),
    ("2026-11-20T18:30", "2026-11-23T09:30"),
    ("2026-11-20T17:59", "2026-11-20T17:59"),
    ("2026-12-25T11:00", "2026-12-28T09:30"),
    ("2026-11-23T08:00", "2026-11-23T09:30"),
])
def test_intake_start(calendar, arrival, expected):
    assert calendar.start(at(arrival)) == at(expected)

def test_friday_1800_medium_ticket_not_late_on_sunday(calendar):
    reply, resolve = deadlines(calendar, calendar.start(at("2026-11-20T18:00")), Policy(270, 1620))
    assert at("2026-11-22T10:00") < reply < resolve


def test_1815_reply_carries_to_next_working_day(calendar):
    start = calendar.start(at("2026-11-20T18:15"))
    assert start == at("2026-11-20T18:15")
    reply, resolve = deadlines(calendar, start, Policy(120, None))
    assert reply == at("2026-11-23T11:15")
    assert resolve == at("2026-11-20T18:30")


def test_business_addition_accrues_until_close(calendar):
    assert calendar.add(at("2026-11-20T17:30"), 60) == at("2026-11-20T18:30")
    assert calendar.add(at("2026-11-20T17:30"), 90) == at("2026-11-23T10:00")


def test_holiday_and_weekend(calendar):
    assert calendar.add(at("2026-12-24T17:30"), 120) == at("2026-12-28T10:30")

def test_pause_crossing_weekend(calendar):
    pauses = [Pause(at("2026-11-20T17:00"), at("2026-11-23T10:00"))]
    reply, resolve = deadlines(calendar, at("2026-11-20T16:00"), Policy(120, 180), pauses)
    assert reply == at("2026-11-20T18:00")
    assert resolve == at("2026-11-23T12:00")

def test_open_pause_freezes_clock_at_supplied_now(calendar):
    pause = Pause(at("2026-11-23T10:30"))
    _, resolve = deadlines(calendar, at("2026-11-23T09:30"), Policy(120, 180), [pause], at("2026-11-24T10:30"))
    assert resolve == at("2026-11-24T12:30")

def test_pause_after_original_deadline_does_not_erase_breach(calendar):
    _, resolve = deadlines(calendar, at("2026-11-23T09:30"), Policy(120, 60), [Pause(at("2026-11-23T12:00"), at("2026-11-24T12:00"))])
    assert resolve == at("2026-11-23T10:30")

def test_urgent_midflight_uses_original_start(calendar):
    start = at("2026-11-23T10:00")
    old = deadlines(calendar, start, Policy(270, 1620))
    new = deadlines(calendar, start, Policy(120, None))
    assert old[1] > at("2026-11-24T10:00")
    assert new == (at("2026-11-23T12:00"), at("2026-11-23T18:30"))
    assert new[1] < at("2026-11-24T10:00")

def test_urgent_pause_extends_same_day_deadline(calendar):
    _, resolve = deadlines(calendar, at("2026-11-23T10:00"), Policy(120, None), [Pause(at("2026-11-23T11:00"), at("2026-11-23T12:00"))])
    assert resolve == at("2026-11-24T10:30")

def test_reopen_boundary_inclusive(calendar):
    resolved = at("2026-11-20T17:30")
    end = calendar.add(resolved, 2700)
    assert can_reopen(calendar, resolved, end)
    assert not can_reopen(calendar, resolved, end + timedelta(microseconds=1))
    assert not can_reopen(calendar, resolved, resolved - timedelta(seconds=1))

def test_autoclose_boundary(calendar):
    waiting = at("2026-11-20T17:30")
    threshold = calendar.add(waiting, 2700)
    assert not should_auto_close(calendar, waiting, threshold - timedelta(seconds=1))
    assert should_auto_close(calendar, waiting, threshold)

@pytest.mark.parametrize("minutes", [0, 1, 30, 540, 1620, 2700])
def test_add_elapsed_roundtrip(calendar, minutes):
    start = at("2026-12-24T17:45")
    assert calendar.minutes(start, calendar.add(start, minutes)) == minutes

def test_reject_naive_time_and_negative_duration(calendar):
    with pytest.raises(ValueError):
        calendar.start(datetime(2026, 11, 23))
    with pytest.raises(ValueError):
        calendar.add(at("2026-11-23T10:00"), -1)

def test_reject_overlapping_pauses(calendar):
    with pytest.raises(ValueError):
        deadlines(calendar, at("2026-11-23T09:30"), Policy(120, 180), [
            Pause(at("2026-11-23T10:00"), at("2026-11-23T12:00")),
            Pause(at("2026-11-23T11:00"), at("2026-11-23T13:00")),
        ])


def test_reopen_at_2700_and_link_at_2701(calendar):
    from frontdesk.business_time import plan_reopen
    resolved = at("2026-11-20T17:30")
    allowed = plan_reopen(calendar, resolved, calendar.add(resolved, 2700), Policy(270, 1620))
    refused = plan_reopen(calendar, resolved, calendar.add(resolved, 2701), Policy(270, 1620))
    assert allowed.action == "reopen"
    assert refused.action == "linked_new_ticket"


def test_reopen_cycle_does_not_inherit_first_cycle_breach(calendar):
    from frontdesk.business_time import plan_reopen
    original = at("2026-11-23T10:00")
    old_due = deadlines(calendar, original, Policy(120, None))[1]
    resolved = at("2026-11-24T10:00")
    assert resolved > old_due
    reopened = at("2026-11-24T11:00")
    plan = plan_reopen(calendar, resolved, reopened, Policy(120, None))
    assert plan.cycle_start == reopened
    assert plan.resolution_due == at("2026-11-24T18:30")
    assert plan.resolution_due > reopened
    assert old_due == at("2026-11-23T18:30")


@pytest.mark.parametrize("operation", ["start", "add", "minutes", "zero"])
def test_calendar_rejects_unseeded_range(calendar, operation):
    from frontdesk.business_time import CalendarRangeError
    with pytest.raises(CalendarRangeError, match="last seeded holiday: 2027-12-25"):
        if operation == "start":
            calendar.start(at("2027-12-26T11:00"))
        elif operation == "add":
            calendar.add(at("2027-12-24T18:00"), 60)
        elif operation == "zero":
            calendar.add(at("2027-12-26T11:00"), 0)
        else:
            calendar.minutes(at("2027-12-24T18:00"), at("2027-12-26T11:00"))


def test_empty_holiday_seed_is_not_a_valid_calendar():
    from frontdesk.business_time import CalendarRangeError
    with pytest.raises(CalendarRangeError):
        Calendar(frozenset()).start(at("2026-11-23T10:00"))


def test_reversed_pause_is_rejected(calendar):
    with pytest.raises(ValueError, match="Invalid or overlapping"):
        deadlines(calendar, at("2026-11-23T09:30"), Policy(120, None), [
            Pause(at("2026-11-23T12:00"), at("2026-11-23T11:00")),
        ])


def test_urgent_pause_after_deadline_preserves_breach(calendar):
    _, due = deadlines(calendar, at("2026-11-23T09:30"), Policy(120, None), [
        Pause(at("2026-11-24T10:00"), at("2026-11-24T11:00")),
    ])
    assert due == at("2026-11-23T18:30")


def test_open_pause_requires_explicit_clock(calendar):
    with pytest.raises(ValueError, match="explicit clock"):
        deadlines(calendar, at("2026-11-23T09:30"), Policy(120, None), [Pause(at("2026-11-23T10:00"))])


def test_open_pause_cannot_be_followed_by_another_pause(calendar):
    with pytest.raises(ValueError):
        deadlines(calendar, at("2026-11-23T09:30"), Policy(120, None), [
            Pause(at("2026-11-23T10:00")),
            Pause(at("2026-11-23T11:00"), at("2026-11-23T12:00")),
        ], at("2026-11-23T10:30"))


def test_elapsed_until_last_seeded_holiday_does_not_walk_beyond_end(calendar):
    assert calendar.minutes(at("2027-12-24T18:00"), at("2027-12-25T18:30")) == 30
    assert calendar.minutes(at("2027-12-25T10:00"), at("2027-12-25T18:30")) == 0
