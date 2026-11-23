// Exercise the shipped refresh, including real request decoding and event reduction.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();
function node(s){if(!nodes.has(s))nodes.set(s,{value:s==='#status-filter'?'all':'',innerHTML:'',textContent:'',hidden:false,open:false,showModal(){this.open=true;},classList:{toggle(){}},addEventListener(){}});return nodes.get(s);}
let active=0,peak=0;const seen=[];
const tickets=Array.from({length:64},(_,i)=>({id:i+1,status:'open',subject:'Ticket '+i,customer_email:'customer@example.com',assignee_id:null,priority:'medium',sla:{is_late:false,resolution_due_at:'2026-11-24T10:00:00+05:30'}}));
const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},sessionStorage:{getItem:()=>null},location:{hash:'#tickets'},setInterval(){},setTimeout,clearTimeout,Intl,Date,console,fetch:async path=>{
 if(path==='/tickets?assignee=all')return {ok:true,status:200,json:async()=>tickets};
 const match=path.match(/^\/tickets\/(\d+)\/events$/);assert.ok(match,path);const id=Number(match[1]);seen.push(id);active++;peak=Math.max(peak,active);
 await new Promise(resolve=>setTimeout(resolve,2));active--;
 return {ok:true,status:200,json:async()=>[{created_at:'2026-11-22T10:00:00Z'},{created_at:'2026-11-23T10:00:00Z'},{created_at:'2026-11-21T10:00:00Z'}]};
}});
vm.runInContext(fs.readFileSync('frontdesk/static/app.js','utf8'),context);
(async()=>{vm.runInContext("state.queue='all';state.agent=1",context);await vm.runInContext('refresh()',context);assert.equal(seen.length,64);assert.equal(new Set(seen).size,64);assert.ok(peak<=4,`Peak event reads: ${peak}`);assert.equal(vm.runInContext('state.lastActivity.size',context),64);assert.ok(vm.runInContext("[...state.lastActivity.values()].every(t=>t==='2026-11-23T10:00:00Z')",context));assert.ok(node('#ticket-list').innerHTML.includes('Ticket 63'));console.log(JSON.stringify({tickets:64,event_requests:seen.length,peak_event_reads:peak,activity:'latest actual event timestamp'}));})().catch(error=>{console.error(error);process.exitCode=1;});
