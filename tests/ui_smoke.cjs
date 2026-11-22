// Run the shipped render functions with a tiny DOM sink; no copied templates.
const fs=require('node:fs'),vm=require('node:vm');
const data=JSON.parse(fs.readFileSync(0,'utf8')),nodes=new Map();
function node(selector){if(!nodes.has(selector))nodes.set(selector,{value:selector==='#status-filter'?'all':'',innerHTML:'',textContent:'',open:false,hidden:false,classList:{toggle(){}},addEventListener(){},showModal(){},focus(){}});return nodes.get(selector);}
const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){},hidden:false},window:{addEventListener(){},scrollTo(){}},sessionStorage:{getItem:()=>null},location:{hash:'#tickets'},setInterval(){},setTimeout(){},clearTimeout(){},Intl,Date,console});
vm.runInContext(fs.readFileSync('frontdesk/static/app.js','utf8'),context);
context.fixture=data;
vm.runInContext(`state.agent=1;state.agents=fixture.agents;state.tickets=fixture.tickets;state.queue='all';state.detail=fixture.detail;state.events=fixture.events;renderList();renderDetail();`,context);
process.stdout.write(JSON.stringify({list:node('#ticket-list').innerHTML,detail:node('#detail').innerHTML}));
