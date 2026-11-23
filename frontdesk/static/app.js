'use strict';
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const date = value => value ? new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Kolkata',weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)).replace(/^(\w+), /,'$1 ') : '—';
const fullDate = value => value ? new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',weekday:'long',day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(value))+' IST' : 'No deadline';
const time = value => `<time ${value?`datetime="${esc(value)}"`:''} title="${esc(fullDate(value))}">${esc(date(value))}</time>`;
const ticketID = id => `FD-${String(id).padStart(4,'0')}`;
const statusText = ticket => ticket.status==='waiting_on_customer'
  ? '<span class="status waiting" title="Waiting on customer"><span class="waiting-dot" aria-hidden="true"></span>Waiting</span>'
  : `<span class="status ${['resolved','closed'].includes(ticket.status)?'muted':''}">${esc(labels[ticket.status])}</span>`;
const istDay = value => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
function relativeTime(value){
  if(!value)return '—';
  const seconds=Math.max(0,Math.floor((Date.now()-new Date(value).getTime())/1000));
  if(seconds<60)return 'Just now';
  if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;
  if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;
  return `${Math.floor(seconds/86400)}d ago`;
}
function dueText(ticket){
  const value=ticket.sla.resolution_due_at;
  if(!value)return '—';
  const clock=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
  const text=istDay(value)===istDay(Date.now())?`<span class="today">Today</span>, ${esc(clock)}`:esc(date(value));
  return `<time datetime="${esc(value)}" title="${esc(fullDate(value))}">${text}</time>${ticket.sla.is_late?'<span class="late-label">Late</span>':''}`;
}
// Presentation order only: keep the API's SLA flags and deadlines authoritative.
function ticketSortGroup(ticket){return ticket.sla.is_late?0:ticket.status==='open'?1:ticket.status==='waiting_on_customer'?2:3;}
function ticketSortDeadline(ticket){
  const resolution=new Date(ticket.sla.resolution_due_at).getTime();
  if(!ticket.sla.is_late)return resolution;
  const overdue=[];
  if(ticket.sla.resolution_breached)overdue.push(resolution);
  if(!ticket.first_replied_at&&ticket.sla.cycle_number===1&&ticket.sla.first_reply_breached)overdue.push(new Date(ticket.sla.first_reply_due_at).getTime());
  return overdue.length?Math.min(...overdue):resolution;
}
function compareTickets(a,b){return ticketSortGroup(a)-ticketSortGroup(b)||ticketSortDeadline(a)-ticketSortDeadline(b)||a.id-b.id;}
const labels = {open:'Open',waiting_on_customer:'Waiting on customer',resolved:'Resolved',closed:'Closed'};
const state = {token:sessionStorage.getItem('frontdesk-key') || '',agent:0,epoch:0,agents:[],tickets:[],lastActivity:new Map(),queue:'me',selected:null,detail:null,events:[],tab:'conversation',mode:'public',draft:'',statusAction:null,statusDraft:'',statusKey:null,statusVersion:null,version:0};
let toastTimer, refreshing = false, refreshAgain = false;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6000);}
async function request(path, {method='GET', body, customerToken, signal, idempotencyKey}={}){
  const headers = customerToken ? {'X-Customer-Token':customerToken} : {'Authorization':`Bearer ${state.token}`};
  if(idempotencyKey) headers['Idempotency-Key']=idempotencyKey;
  if(body !== undefined) headers['Content-Type']='application/json';
  const epoch=state.epoch;
  const response=await fetch(path,{method,headers,body:body === undefined ? undefined : JSON.stringify(body),signal});
  const data=await response.json().catch(()=>({detail:'Unexpected server response'}));
  if(response.status===401)clearSession();
  if(epoch!==state.epoch&&response.ok){const error=new Error('Please sign in again.');error.status=401;throw error;}
  if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:response.status===422?'Please check the form fields.':data.detail?.message || 'Request failed');error.status=response.status;error.detail=data.detail;throw error;}
  return data;
}
function visibleTickets(){const query=$('#search').value.trim().toLowerCase(),status=$('#status-filter').value;return state.tickets.filter(t=>(state.queue==='all'||state.queue==='me'&&t.assignee_id===state.agent||state.queue==='unassigned'&&t.assignee_id===null)&&(status==='all'||status==='active'&&['open','waiting_on_customer'].includes(t.status)||t.status===status)&&`${t.id} ${t.subject} ${t.customer_email}`.toLowerCase().includes(query)).sort(compareTickets);}
function renderList(){
  const rows=visibleTickets();
  $('#my-count').textContent=state.tickets.filter(t=>t.assignee_id===state.agent&&['open','waiting_on_customer'].includes(t.status)).length;
  $('#unassigned-count').textContent=state.tickets.filter(t=>t.assignee_id===null&&['open','waiting_on_customer'].includes(t.status)).length;
  $('#all-count').textContent=state.tickets.length;
  const mine=state.queue==='me';
  $('#list-page').classList.toggle('mine',mine);
  $('#assignee-heading').hidden=mine;
  $('#ticket-list').innerHTML=rows.length?rows.map(t=>{
    const activity=state.lastActivity.get(t.id);
    return `<tr class="ticket-row" data-ticket="${t.id}"><td class="ticket-number">${ticketID(t.id)}</td><td class="subject"><a href="#ticket/${t.id}" title="${esc(t.subject)}">${esc(t.subject)}</a></td><td class="row-status">${statusText(t)}</td><td class="row-priority ${t.priority==='urgent'?'urgent':'muted'}">${esc(t.priority[0].toUpperCase()+t.priority.slice(1))}</td>${mine?'':`<td class="row-assignee">${esc(state.agents.find(a=>a.id===t.assignee_id)?.name || 'Unassigned')}</td>`}<td class="row-activity"><time ${activity?`datetime="${esc(activity)}"`:''} title="${activity?esc(fullDate(activity)):'No activity recorded'}">${relativeTime(activity)}</time></td><td class="row-due ${t.sla.is_late?'danger-text':''}">${dueText(t)}</td></tr>`;
  }).join(''):`<tr class="empty-row"><td colspan="${mine?6:7}" class="empty">No tickets here.</td></tr>`;
  $('#queue-footer').textContent=`${rows.length} ticket${rows.length===1?'':'s'} · Late tickets first · j / k to move, Enter to open`;
}
const EVENT_LABELS = {created:'Ticket created',claimed:'Ticket claimed',reassigned:'Ticket reassigned',linked_ticket_created:'Follow-up ticket linked',public_reply:'Public agent reply',internal_note_added:'Internal note added',status_changed:'Status changed',priority_changed:'Priority changed',paused:'Resolution clock paused',resumed:'Waiting interval ended',auto_closed:'Automatically closed',reopened:'New resolution cycle opened'};
function eventLabel(event){return event.event_type==='public_reply'&&event.actor==='customer'?'Customer reply':EVENT_LABELS[event.event_type] || 'Unrecognized event';}
function actorName(actor){if(actor.startsWith('agent:'))return state.agents.find(a=>a.id===Number(actor.split(':')[1]))?.name || actor;return actor==='system'?'System':'Customer';}
function renderActivity(){return state.events.map(e=>`<div class="event">${time(e.created_at)}<span>${esc(eventLabel(e))} · ${esc(actorName(e.actor))}${e.after_value?.source?' · Source: '+esc(e.after_value.source):''}${e.after_value?.previous_ticket_id?' · Linked from '+ticketID(e.after_value.previous_ticket_id):''}${e.after_value?.assignee_id?' · '+esc(actorName('agent:'+e.after_value.assignee_id)):''}${e.after_value?.status?` · ${esc(labels[e.after_value.status] || e.after_value.status)}`:''}${e.event_type==='priority_changed'?` · ${esc(e.before_value?.priority)} → ${esc(e.after_value.priority)}`:''}</span></div>`).join('') || '<p class="empty">No activity yet.</p>';}
function renderThread(){
  const t=state.detail;const messages=[...t.messages,...t.internal_notes.map(n=>({...n,author_type:'agent'}))].sort((a,b)=>new Date(a.created_at)-new Date(b.created_at)||a.id-b.id);
  return messages.map(m=>`<article class="message ${m.visibility==='internal'?'internal':''}"><div class="message-header"><strong>${esc(m.author_type==='customer'?'Customer':state.agents.find(a=>a.id===m.agent_id)?.name || 'Agent')}</strong>${time(m.created_at)}${m.visibility==='internal'?'<span class="private-label">Team-only</span>':''}</div><p class="message-body">${esc(m.body)}</p></article>`).join('') || '<p class="empty">No messages yet.</p>';
}
function renderDetail(){
  const t=state.detail;if(!t)return;
  const activityOpen=$('#activity')?.open,active=['open','waiting_on_customer'].includes(t.status),mine=t.assignee_id===state.agent,owner=state.agents.find(a=>a.id===t.assignee_id)?.name || 'Unassigned';
  const customerURL=`/customer#${t.id}:${t.customer_token}`;
  $('#detail').innerHTML=`<header class="detail-header"><div class="detail-navigation"><a href="#tickets">← Tickets</a><details class="overflow"><summary aria-label="Ticket actions">…</summary><div class="menu">${t.customer_token?`${active?'<button id="simulate">Simulate customer reply</button>':''}<button id="export">Export CSV</button><a href="${esc(customerURL)}" target="_blank" rel="noopener">Customer view</a>`:''}</div></details></div><p class="ticket-number">${ticketID(t.id)}</p><h1 tabindex="-1">${esc(t.subject)}</h1><p class="detail-customer">${esc(t.customer_email)} · Created ${time(t.created_at)} · Cycle ${t.sla.cycle_number}</p></header>
  <div class="ticket-controls"><label>Status <select id="ticket-status" class="${t.status==='waiting_on_customer'?'waiting':''}" aria-label="Ticket status" ${active&&mine?'':'disabled'} title="${esc(mine?'Change ticket status':t.assignee_id?'Assigned to '+owner+'. Only '+owner+' can resolve or wait.':'Claim this ticket first')}">${Object.entries(labels).map(([key,value])=>`<option value="${key}" ${key===t.status?'selected':''} ${key==='closed'?'disabled':''}>${value}</option>`).join('')}</select></label><label>Priority <select id="ticket-priority" class="${t.priority==='urgent'?'urgent':''}" aria-label="Ticket priority" ${active&&(!t.assignee_id||mine)?'':'disabled'} title="${esc(t.assignee_id&&!mine?'Assigned to '+owner+'. Only '+owner+' can change priority.':'Change priority')}">${['urgent','medium','small'].map(p=>`<option ${p===t.priority?'selected':''} value="${p}">${p[0].toUpperCase()+p.slice(1)}</option>`).join('')}</select></label><div class="assignee-control"><span class="field-label">Assignee</span><span id="ticket-assignee" aria-label="Ticket assignee">${esc(owner)}</span></div>${active&&!t.assignee_id?'<button id="claim" class="primary claim-button" type="button">Take this ticket</button>':''}<div class="deadline"><span>First reply ${t.first_replied_at?'sent':'due'}</span><span class="${!t.first_replied_at&&t.sla.first_reply_breached?'danger-text':''}">${time(t.first_reply_at || t.sla.first_reply_due_at)}${t.first_reply_actor?` · ${esc(actorName(t.first_reply_actor))}`:''}</span></div><div class="deadline"><span>Resolution due${t.status==='waiting_on_customer'?' · paused':''}</span><span class="${t.sla.resolution_breached?'danger-text':''}">${time(t.sla.resolution_due_at)}${t.sla.resolution_breached?' <span class="late-label">Late</span>':''}</span></div>${!active?'<button id="reopen">Reopen ticket</button>':''}<span class="breached-targets">${t.sla.breached_targets?.length?`Breached: ${esc(t.sla.breached_targets.join(', ').replaceAll('_',' '))}`:''}</span></div>
  <section class="thread" aria-label="Conversation">${renderThread()}</section>
  <details id="activity" class="activity" ${activityOpen?'open':''}><summary>Activity <span>${state.events.length}</span></summary>${renderActivity()}</details>
  ${state.statusAction?`<form id="status-message-form" class="composer"><label for="status-message">${state.statusAction==='resolved'?'Message to customer':'Question to customer'}</label><textarea id="status-message" required maxlength="10000">${esc(state.statusDraft)}</textarea><button type="submit" class="primary">${state.statusAction==='resolved'?'Resolve ticket':'Send and wait'}</button><button type="button" id="cancel-status">Cancel</button></form>`:''}
  <form id="reply-form" class="composer ${state.mode==='internal'?'internal':''}"><div class="mode-switch" aria-label="Reply visibility"><button type="button" data-mode="public" class="${state.mode==='public'?'active':''}" aria-pressed="${state.mode==='public'}">Reply to customer</button><span aria-hidden="true">|</span><button type="button" data-mode="internal" class="${state.mode==='internal'?'active':''}" aria-pressed="${state.mode==='internal'}">Internal note</button></div><textarea id="reply-body" aria-label="${state.mode==='internal'?'Internal note':'Public reply'}" placeholder="${state.mode==='internal'?'Leave context for your team…':'Write a reply to the customer…'}" maxlength="10000" required ${state.mode==='public'&&(!active||!mine)?'disabled':''}>${esc(state.draft)}</textarea><div class="composer-actions"><p class="composer-hint">${state.mode==='internal'?'Only your team can see this note.':!active?'Reopen this ticket before sending a public reply.':!mine?'Take this ticket to send a public reply.':'This reply will be visible to the customer.'}</p><button class="primary" type="submit" ${state.mode==='public'&&(!active||!mine)?'disabled':''}>${state.mode==='internal'?'Add note':'Send reply'}</button></div></form>`;
  $('#list-page').hidden=true;$('#detail').hidden=false;
}
function showList(){state.selected=null;state.detail=null;state.version++;$('#list-page').hidden=false;$('#detail').hidden=true;renderList();}
async function selectTicket(id){state.selected=id;state.draft='';state.replyKey=null;state.mode='public';state.statusAction=null;state.statusDraft='';state.tab='conversation';$('#detail').innerHTML='<p class="empty">Loading ticket…</p>';$('#list-page').hidden=true;$('#detail').hidden=false;if(location.hash!==`#ticket/${id}`)location.hash=`ticket/${id}`;await loadDetail();$('#detail h1')?.focus({preventScroll:true});window.scrollTo(0,0);}
function route(){const match=location.hash.match(/^#ticket\/(\d+)$/);if(match){if(state.selected!==Number(match[1]))selectTicket(Number(match[1])).catch(handleError);}else showList();}
window.addEventListener('hashchange',route);
async function loadDetail(){if(!state.selected)return;const version=++state.version,id=state.selected;const [detail,events]=await Promise.all([request(`/tickets/${id}`),request(`/tickets/${id}/events`)]);if(version!==state.version||id!==state.selected)return;if(detail.assignee_id===state.agent){const access=await request(`/tickets/${id}/customer-access`);if(version!==state.version||id!==state.selected)return;detail.customer_token=access.customer_token;}state.detail=detail;state.events=events;renderDetail();}
async function refresh(){if(refreshing){refreshAgain=true;return;}refreshing=true;try{const tickets=await request('/tickets?assignee=all');
  // Use existing event reads; do not substitute ticket creation/update timestamps.
  const activity=await Promise.all(tickets.map(async ticket=>{
    const events=await request(`/tickets/${ticket.id}/events`);
    const latest=events.reduce((last,event)=>!last||new Date(event.created_at)>new Date(last)?event.created_at:last,null);
    return [ticket.id,latest];
  }));
  state.tickets=tickets;state.lastActivity=new Map(activity);renderList();if(state.selected)await loadDetail();else if(location.hash.startsWith('#ticket/'))route();}catch(error){handleError(error);}finally{refreshing=false;if(refreshAgain){refreshAgain=false;await refresh();}}}
function showLogin(){
  $('#main').hidden=true;$('.topbar').hidden=true;
  if(!$('#login-dialog').open)$('#login-dialog').showModal();
}
function clearSession(){
  state.epoch++;state.token='';state.agent=0;state.agents=[];state.tickets=[];state.detail=null;state.selected=null;state.events=[];state.lastActivity=new Map();state.draft='';state.version++;
  sessionStorage.clear();$('#detail').innerHTML='';$('#ticket-list').innerHTML='';$('#agent').textContent='';
  if($('#create-dialog').open)$('#create-dialog').close();
  showLogin();
}
function handleError(error){if(error.status===401)clearSession();toast(error.message);}
async function mutate(path,body,options={}){const selected=state.selected;try{await request(path,{method:'POST',body,...options});await refresh();return true;}catch(error){if(error.status===409&&error.detail?.assignee_name){toast(`${error.detail.assignee_name} already took this ticket. The ticket has been refreshed.`);if(selected)await refresh();}else{handleError(error);await refresh();}return false;}}
async function connect(){
  const me=await request('/auth/me');state.agent=me.id;$('#agent').textContent=me.name;
  state.agents=await request('/agents');await refresh();
  if(!state.token)throw new Error('Please sign in again.');
  $('#main').hidden=false;$('.topbar').hidden=false;
}
$('#login-form').addEventListener('submit',async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  try{
    const result=await request('/auth/login',{method:'POST',body:{email:$('#login-email').value,password:$('#login-password').value}});
    state.token=result.token;sessionStorage.setItem('frontdesk-key',state.token);
    await connect();$('#login-dialog').close();$('#login-error').textContent='';
  }catch(error){$('#login-error').textContent=error.status===429?'Too many sign-in attempts. Try again in 10 minutes.':'Unable to sign in. Check your email and password.';}
  finally{$('#login-password').value='';button.disabled=false;}
});
$('#login-dialog').addEventListener('cancel',e=>e.preventDefault());
$('#signout').addEventListener('click',async()=>{try{await request('/auth/logout',{method:'POST'});}catch(error){handleError(error);}finally{clearSession();}});
document.querySelectorAll('[data-queue]').forEach(button=>button.addEventListener('click',()=>{state.queue=button.dataset.queue;document.querySelectorAll('[data-queue]').forEach(b=>b.classList.toggle('selected',b===button));document.querySelectorAll('[data-queue]').forEach(b=>{if(b===button)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});location.hash='tickets';showList();}));
$('#search').addEventListener('input',()=>{if(state.selected){location.hash='tickets';showList();}else renderList();});$('#status-filter').addEventListener('change',renderList);$('#refresh').addEventListener('click',refresh);
$('#ticket-list').addEventListener('click',e=>{const row=e.target.closest('[data-ticket]');if(row&&!e.target.closest('a'))selectTicket(Number(row.dataset.ticket)).catch(handleError);});
$('#new-ticket').addEventListener('click',()=>$('#create-dialog').showModal());document.querySelectorAll('.close-dialog').forEach(b=>b.addEventListener('click',()=>$('#create-dialog').close()));
$('#create-form').addEventListener('submit',async e=>{e.preventDefault();e.submitter.disabled=true;try{const data=Object.fromEntries(new FormData(e.target));const ticket=await request('/tickets',{method:'POST',body:data});$('#create-dialog').close();e.target.reset();state.queue='unassigned';document.querySelector('[data-queue="unassigned"]').click();await refresh();await selectTicket(ticket.id);toast('Ticket created. Take ownership to send a reply.');}catch(error){$('#create-error').textContent=error.message;}finally{e.submitter.disabled=false;}});
$('#detail').addEventListener('input',e=>{if(e.target.id==='status-message'){state.statusDraft=e.target.value;state.statusKey=null;}if(e.target.id==='reply-body'){state.draft=e.target.value;state.replyKey=null;}});
$('#detail').addEventListener('change',async e=>{if(e.target.id==='ticket-status'){
  const status=e.target.value,payload={status,version:state.detail.version};
  if(status==='resolved'||status==='waiting_on_customer'){state.statusAction=status;state.statusDraft=state.mode==='public'?state.draft:'';state.statusVersion=state.detail.version;state.statusKey=null;renderDetail();$('#status-message').focus();return;}
  if(await mutate(`/tickets/${state.selected}/status`,payload)){if(payload.body){state.draft='';renderDetail();}}
}if(e.target.id==='ticket-priority')await mutate(`/tickets/${state.selected}/priority`,{priority:e.target.value});});
$('#detail').addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try{if(b.id==='cancel-status'){state.statusAction=null;state.statusDraft='';renderDetail();return;}if(b.dataset.tab){state.tab=b.dataset.tab;renderDetail();return;}if(b.dataset.mode){state.mode=b.dataset.mode;state.replyKey=null;renderDetail();$('#reply-body')?.focus();return;}if(!['claim','reopen','simulate','export'].includes(b.id))return;b.disabled=true;const t=state.detail;if(b.id==='claim'){if(await mutate(`/tickets/${t.id}/claim`))toast('Ticket assigned to you.');}if(b.id==='reopen'){const result=await request(`/tickets/${t.id}/agent-reopen`,{method:'POST'});$('#status-filter').value='all';await refresh();await selectTicket(result.ticket.id);toast(result.action==='reopen'?'A new resolution cycle has started.':'Reopen window expired. A linked ticket was created.');}if(b.id==='simulate'){const body=prompt('Customer reply (visible in the public conversation):');if(body?.trim()){await mutate(`/tickets/${t.id}/customer-reply`,{body:body.trim()},{customerToken:t.customer_token});toast('Customer reply added. Any waiting clock has resumed.');}}if(b.id==='export'){const response=await fetch('/export.csv',{headers:{'X-Customer-Token':t.customer_token}});if(response.status===401)clearSession();if(!response.ok)throw new Error('Export failed');const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`frontdesk-${t.id}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}catch(error){handleError(error);}finally{b.disabled=false;}});
$('#detail').addEventListener('submit',async e=>{if(e.target.id==='status-message-form'){e.preventDefault();if(!state.statusDraft.trim())return;e.submitter.disabled=true;try{await request(`/tickets/${state.selected}/status`,{method:'POST',body:{status:state.statusAction,body:state.statusDraft,version:state.statusVersion},idempotencyKey:state.statusKey ||= crypto.randomUUID()});state.statusAction=null;state.statusDraft='';state.draft='';await refresh();}catch(error){handleError(error);}finally{e.submitter.disabled=false;}return;}if(e.target.id!=='reply-form')return;e.preventDefault();e.submitter.disabled=true;const draft=state.draft,mode=state.mode;try{await request(`/tickets/${state.selected}/messages`,{method:'POST',body:{body:draft,visibility:mode},idempotencyKey:state.replyKey ||= crypto.randomUUID()});state.draft='';state.replyKey=null;await refresh();toast(mode==='internal'?'Internal note added. Only your team can see it.':'Public reply sent.');}catch(error){state.draft=draft;handleError(error);}finally{e.submitter.disabled=false;}});
if(state.token)connect().catch(handleError);else showLogin();
// Keep SLA indicators and projected paused deadlines current without losing drafts.
setInterval(()=>{if(state.token&&!document.hidden&&!state.draft&&!state.statusAction&&!$('#create-dialog').open)refresh();},60000);

// List navigation is presentation-only; native links also support opening in a new tab.
document.addEventListener('keydown',e=>{
  if(e.key==='Escape')document.querySelectorAll('.overflow[open]').forEach(menu=>menu.open=false);
  if(state.selected||e.altKey||e.ctrlKey||e.metaKey||e.target.closest('input,textarea,select,dialog,[contenteditable="true"],.overflow'))return;
  if(!['j','k'].includes(e.key))return;
  const links=[...document.querySelectorAll('.subject a')];if(!links.length)return;
  e.preventDefault();let index=links.indexOf(document.activeElement);index=index<0?(e.key==='j'?0:links.length-1):Math.max(0,Math.min(links.length-1,index+(e.key==='j'?1:-1)));links[index].focus();
});
document.addEventListener('click',e=>document.querySelectorAll('.overflow[open]').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;}));
