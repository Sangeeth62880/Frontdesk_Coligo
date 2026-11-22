"""Independent minute-stepping oracle; no production calendar calls in reference."""
from datetime import date, datetime, time, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from frontdesk.business_time import (
    ZONE,
    Calendar,
    CalendarRangeError,
    Pause,
    Policy,
    can_reopen,
    deadlines,
    should_auto_close,
)

MINUTE = timedelta(minutes=1)


def ref_working(instant, holidays):
    return instant.weekday() < 5 and instant.date() not in holidays and time(9,30) <= instant.time() < time(18,30)


def ref_start(instant, holidays):
    while not ref_working(instant, holidays):
        instant += MINUTE
    return instant


def ref_deadline(start, minutes, holidays, pauses=()):
    cursor = start
    left = minutes
    while left:
        if ref_working(cursor, holidays) and not any(p.paused_at <= cursor < p.resumed_at for p in pauses):
            left -= 1
        cursor += MINUTE
    return cursor


@settings(max_examples=2000, deadline=None, derandomize=True)
@given(day=st.dates(min_value=date(2024,1,1), max_value=date(2026,11,30)),
       minute=st.integers(0,1439), target=st.integers(1,2700),
       holiday_offsets=st.sets(st.integers(0,18),max_size=7),
       pause_offset=st.integers(0,6*1440), pause_length=st.integers(0,4*1440))
def test_independent_minute_oracle_and_pause_priority_monotonicity(day, minute, target, holiday_offsets, pause_offset, pause_length):
    holidays = frozenset({date(2027,12,25)} | {day+timedelta(days=x) for x in holiday_offsets})
    calendar = Calendar(holidays)
    arrival = datetime.combine(day, time(), ZONE)+minute*MINUTE
    start = ref_start(arrival, holidays)
    assert calendar.start(arrival) == start
    expected = ref_deadline(start,target,holidays)
    assert calendar.add(start,target) == expected
    assert expected >= start
    assert ref_working(expected,holidays) or expected.time() == time(18,30)
    pause = Pause(start+pause_offset*MINUTE, start+(pause_offset+pause_length)*MINUTE)
    first, due = deadlines(calendar,start,Policy(120,target),[pause])
    oracle = ref_deadline(start,target,holidays,[pause])
    assert due == oracle
    assert due >= expected and first == calendar.add(start,120)
    assert ref_working(due,holidays) or due.time() == time(18,30)
    # Paused minutes count only up to the actual deadline, never after breach.
    overlap = calendar.minutes(max(start,pause.paused_at),min(due,pause.resumed_at)) if pause.paused_at < due else 0
    assert calendar.minutes(start,due) == target+overlap
    stricter = deadlines(calendar,start,Policy(120,max(1,target//2)),[pause])[1]
    assert stricter <= due
    later = due+timedelta(days=3)
    assert not can_reopen(calendar,start,later) or can_reopen(calendar,start,due)
    assert not should_auto_close(calendar,start,due) or should_auto_close(calendar,start,later)


@pytest.mark.parametrize('minutes',[2699,2700,2701])
def test_reopen_autoclose_threshold_table(minutes):
    calendar=Calendar(frozenset({date(2026,11,27),date(2026,11,30),date(2027,12,25)}))
    start=datetime(2026,11,26,9,30,tzinfo=ZONE)
    now=calendar.add(start,minutes)
    assert can_reopen(calendar,start,now) == (minutes <= 2700)
    assert should_auto_close(calendar,start,now) == (minutes >= 2700)


@pytest.mark.parametrize('minutes',[119,120,121])
def test_urgent_reply_threshold_table(minutes):
    calendar=Calendar(frozenset({date(2027,12,25)}))
    start=datetime(2026,11,20,18,tzinfo=ZONE)
    due=deadlines(calendar,start,Policy(120,None))[0]
    assert (calendar.add(start,minutes) > due) == (minutes > 120)


def test_leap_year_company_holiday_and_range():
    calendar=Calendar(frozenset({date(2027,1,1),date(2027,12,25)}))
    leap=datetime(2024,2,29,18,29,tzinfo=ZONE)
    assert calendar.add(leap,2) == datetime(2024,3,1,9,31,tzinfo=ZONE)
    assert calendar.add(datetime(2026,12,31,18,29,tzinfo=ZONE),2) == datetime(2027,1,4,9,31,tzinfo=ZONE)
    assert len({datetime(y,m,1,tzinfo=ZONE).utcoffset() for y in (2024,2026,2027) for m in range(1,13)}) == 1
    with pytest.raises(CalendarRangeError):
        calendar.start(datetime(2027,12,25,10,tzinfo=ZONE))
