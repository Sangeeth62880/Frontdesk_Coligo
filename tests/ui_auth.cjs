// Execute the shipped handlers, including fetch and session storage behavior.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),storage=new Map(),requests=[];
function node(selector){
  if(!nodes.has(selector))nodes.set(selector,{value:'',innerHTML:'',textContent:'',open:false,hidden:false,disabled:false,listeners:{},classList:{toggle(){}},
    addEventListener(type,handler){this.listeners[type]=handler;},showModal(){this.open=true;},close(){this.open=false;},focus(){}});
  return nodes.get(selector);
}
let loginStatus=200,apiStatus=200;
const context=vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){},hidden:false},window:{addEventListener(){},scrollTo(){}},
  sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),clear:()=>storage.clear()},location:{hash:'#tickets'},
  setInterval(){},setTimeout(){},clearTimeout(){},Intl,Date,console,
  fetch:async(path,options)=>{
    requests.push({path,...options});
    assert(!Object.hasOwn(options.headers,'X-Agent-Id'));
    let status=apiStatus,data=[];
    if(path==='/auth/login'){status=loginStatus;data=status===200?{token:'a'.repeat(64),agent:{id:2,name:'Arun'}}:{detail:'Internal server detail'};}
    else if(path==='/auth/me')data={id:2,name:'Arun'};
    else if(path==='/agents')data=[{id:2,name:'Arun'}];
    else if(path==='/auth/logout')data={ok:true};
    return {status,ok:status<400,json:async()=>data};
  }});
vm.runInContext(fs.readFileSync('frontdesk/static/app.js','utf8'),context);
const state=()=>vm.runInContext('state',context);
async function login(){node('#login-email').value='arun@arvo.example';node('#login-password').value='private-password';await node('#login-form').listeners.submit({preventDefault(){},submitter:node('button')});}
(async()=>{
  assert(node('#login-dialog').open&&node('#main').hidden);
  await login();assert.equal(state().agent,2);assert.equal(node('#agent').textContent,'Arun');assert(!node('#login-dialog').open);
  assert.equal(storage.get('frontdesk-key'),'a'.repeat(64));assert.equal(node('#login-password').value,'');
  await node('#signout').listeners.click();assert(requests.some(r=>r.path==='/auth/logout'&&r.method==='POST'));
  assert.equal(storage.size,0);assert.equal(state().token,'');assert(node('#login-dialog').open);
  loginStatus=401;await login();assert.equal(node('#login-error').textContent,'Unable to sign in. Check your email and password.');
  loginStatus=429;await login();assert(node('#login-error').textContent.includes('10 minutes'));
  loginStatus=200;await login();apiStatus=401;
  await assert.rejects(vm.runInContext("request('/tickets')",context));
  assert.equal(storage.size,0);assert.equal(state().agent,0);assert(node('#main').hidden&&node('#login-dialog').open);
  process.stdout.write('Login UI lifecycle passed\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
