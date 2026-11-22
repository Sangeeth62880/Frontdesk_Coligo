from datetime import date, datetime, timedelta
import pytest
from frontdesk.business_time import Calendar, Pause, Policy, deadlines, can_reopen, should_auto_close
from tests.test_business_time import at
from tests.test_mutations import create, event_types

@pytest.fixture
def cal():
    return Calendar(frozenset({date(2027,12,25)}))

@pytest.mark.parametrize('clock,expected', [('09:29','2026-11-23T09:30'),('09:30','2026-11-23T09:30'),('18:29','2026-11-23T18:29'),('18:30','2026-11-24T09:30'),('18:31','2026-11-24T09:30')])
def test_open_close_arrivals(cal,clock,expected):
    assert cal.start(at('2026-11-23T'+clock))==at(expected)

@pytest.mark.parametrize('arrival', ['2026-11-21T11:00','2026-11-22T11:00','2026-11-23T11:00'])
def test_weekend_and_monday_holiday_arrivals(arrival):
    cal=Calendar(frozenset({date(2026,11,23),date(2027,12,25)}))
    assert cal.start(at(arrival))==at('2026-11-24T09:30')

@pytest.mark.parametrize('holidays,due', [
    ({date(2026,11,23)},'2026-11-24T10:30'),
    ({date(2026,11,21)},'2026-11-23T10:30'),
    ({date(2026,11,23),date(2026,11,24)},'2026-11-25T10:30'),
])
def test_holidays_between_friday_and_next_opening(holidays,due):
    cal=Calendar(frozenset(holidays|{date(2027,12,25)}))
    assert cal.add(at('2026-11-20T18:00'),90)==at(due)


def test_five_working_days_exclude_holiday_and_weekend():
    cal=Calendar(frozenset({date(2026,11,25),date(2027,12,25)}))
    start=at('2026-11-20T17:00')
    due=at('2026-11-30T17:00')
    assert cal.add(start,2700)==due
    assert cal.minutes(start,due)==2700
    assert can_reopen(cal,start,due)
    assert not can_reopen(cal,start,cal.add(start,2701))
    assert not should_auto_close(cal,start,cal.add(start,2699))
    assert should_auto_close(cal,start,due)

@pytest.mark.parametrize('pauses,expected', [
    ([Pause(at('2026-11-20T20:00'),at('2026-11-23T10:30'))],'2026-11-23T12:30'),
    ([Pause(at('2026-11-21T10:00'),at('2026-11-22T14:00'))],'2026-11-23T11:30'),
    ([Pause(at('2026-11-20T18:00'),at('2026-11-20T18:15')),Pause(at('2026-11-23T10:00'),at('2026-11-23T10:30'))],'2026-11-23T12:15'),
])
def test_outside_weekend_multiple_pauses(cal,pauses,expected):
    first,resolution=deadlines(cal,at('2026-11-20T17:30'),Policy(120,180),pauses)
    assert first==at('2026-11-23T10:30')
    assert resolution==at(expected)

@pytest.mark.parametrize('operation', ['start','add','minutes_start','minutes_end','deadline_start','deadline_now','pause_start','pause_end','reopen_start','reopen_now','close_start','close_now'])
def test_naive_rejected_everywhere(cal,operation):
    aware=at('2026-11-23T10:00'); naive=datetime(2026,11,23,11)
    calls={
        'start':lambda:cal.start(naive), 'add':lambda:cal.add(naive,0),
        'minutes_start':lambda:cal.minutes(naive,aware),'minutes_end':lambda:cal.minutes(aware,naive),
        'deadline_start':lambda:deadlines(cal,naive,Policy(120,180)),
        'deadline_now':lambda:deadlines(cal,aware,Policy(120,180),now=naive),
        'pause_start':lambda:deadlines(cal,aware,Policy(120,180),[Pause(naive,aware)]),
        'pause_end':lambda:deadlines(cal,aware,Policy(120,180),[Pause(aware,naive)]),
        'reopen_start':lambda:can_reopen(cal,naive,aware),'reopen_now':lambda:can_reopen(cal,aware,naive),
        'close_start':lambda:should_auto_close(cal,naive,aware),'close_now':lambda:should_auto_close(cal,aware,naive)}
    with pytest.raises(ValueError,match='Timezone-aware'):
        calls[operation]()


def test_independent_clocks_and_friday_medium_not_late(harness,agent_headers):
    c,_,now=harness
    now[0]=at('2026-11-20T18:00')
    medium=create(c,agent_headers)
    urgent=create(c,agent_headers,'urgent')
    for instant in ['2026-11-21T12:00','2026-11-22T12:00','2026-11-23T09:00']:
        now[0]=at(instant)
        assert not c.get(f'/tickets/{medium["id"]}',headers=agent_headers).json()['sla']['is_late']
        sla=c.get(f'/tickets/{urgent["id"]}',headers=agent_headers).json()['sla']
        assert sla['resolution_breached'] and not sla['first_reply_breached']
    now[0]=at('2026-11-23T13:30') # 270 working minutes after Friday 18:00
    assert not c.get(f'/tickets/{medium["id"]}',headers=agent_headers).json()['sla']['is_late']
    now[0]+=timedelta(seconds=1)
    assert c.get(f'/tickets/{medium["id"]}',headers=agent_headers).json()['sla']['breached_targets']==['first_reply']


def test_priority_paused_replied_and_sticky_downgrade(harness,agent_headers):
    c,_,now=harness
    t=create(c,agent_headers);p=f'/tickets/{t["id"]}'
    c.post(p+'/claim',headers=agent_headers)
    c.post(p+'/messages',headers=agent_headers,json={'body':'First'})
    now[0]+=timedelta(hours=1)
    c.post(p+'/status',headers=agent_headers,json={"version": c.get((p+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'waiting_on_customer','body':'Question'})
    now[0]+=timedelta(hours=1)
    result=c.post(p+'/priority',headers=agent_headers,json={'priority':'urgent'})
    assert result.status_code==200
    assert result.json()['sla']['resolution_due_at']==at('2026-11-24T10:30').isoformat()
    assert result.json()['sla']['first_reply_due_at']==at('2026-11-23T12:00').isoformat()
    c.post(p+'/customer-reply',headers={'X-Customer-Token':t['customer_token']},json={'body':'Answer'})
    now[0]=at('2026-11-24T11:00')
    assert c.get(p,headers=agent_headers).json()['sla']['resolution_breached']
    result=c.post(p+'/priority',headers=agent_headers,json={'priority':'small'})
    assert result.json()['sla']['resolution_breached']
    assert result.json()['sla']['resolution_due_at']>now[0].isoformat()
    c.post(p+'/status',headers=agent_headers,json={"version": c.get((p+'/status').removesuffix("/status"), headers=agent_headers).json().get("version", 0), 'status':'resolved'})
    assert c.post(p+'/priority',headers=agent_headers,json={'priority':'medium'}).status_code==409


def test_reopen_2700_remains_inclusive_during_closed_hours(cal):
    resolved=at('2026-11-20T18:30')
    assert cal.minutes(resolved,at('2026-11-29T12:00'))==2700
    assert can_reopen(cal,resolved,at('2026-11-29T12:00'))
    assert not can_reopen(cal,resolved,at('2026-11-30T09:31'))
