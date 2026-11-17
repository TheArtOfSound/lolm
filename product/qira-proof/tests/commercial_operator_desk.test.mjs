import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {File} from "node:buffer";
import {handleOperatorRequest} from "../commercial/operator_desk.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
if(!globalThis.File)globalThis.File=File;
const host="https://ops.proof.imagineqira.com",sid="cs_live_operator123456789012345",identity={sub:"cloudflare_user_0123456789",email:"operator@example.invalid"};
class DB{
 constructor(){this.order={session_id:sid,status:"paid",refund_amount:0,state:"awaiting_authorization",repository:"Test/repo",contact_email:"buyer@example.invalid"};this.report=null;this.actions=[];}
 prepare(sql){const db=this;return {bind(...args){return {
  async first(){
   if(sql.startsWith("SELECT o.session_id"))return db.order.session_id===args[0]?{...db.order}:null;
   if(sql.startsWith("SELECT session_id FROM qira_deliverables"))return db.report?{session_id:sid}:null;
   if(sql.startsWith("UPDATE qira_intakes SET state=?")){const [next,s,old]=args;if(s!==sid||db.order.state!==old||db.order.status!=="paid"||db.order.refund_amount)return null;db.order.state=next;return {session_id:sid};}
   if(sql.startsWith("UPDATE qira_deliverables SET revoked_at=?")){if(!db.report||db.report.revoked_at!=null)return null;db.report.revoked_at=args[0];return {session_id:sid};}
   throw Error("unexpected first "+sql.slice(0,80));
  },
  async all(){
   if(sql.startsWith("SELECT o.session_id"))return {success:true,results:[{...db.order,...(db.report||{})}]};
   if(sql.startsWith("SELECT session_id,action"))return {success:true,results:[...db.actions].reverse()};
   throw Error("unexpected all "+sql.slice(0,80));
  },
  async run(){
   if(sql.startsWith("INSERT INTO qira_operator_audit")){const [id,s,sub,action,detail,t]=args;db.actions.push({id,session_id:s,actor_sub:sub,action,detail,created_at:t});return {success:true};}
   if(sql.startsWith("UPDATE qira_intakes SET state='in_review'")){db.order.state="in_review";return {success:true};}
   if(sql.startsWith("DELETE FROM qira_deliverables")){db.report=null;return {success:true};}
   throw Error("unexpected run "+sql.slice(0,80));
  }
 };}};}
 async batch(statements){
  let results=[];
  for(const {sql,args} of statements){
   let changes=0;
   if(sql.startsWith("INSERT INTO qira_deliverables")){
    if(!this.report&&this.order.status==="paid"&&this.order.refund_amount===0&&this.order.state==="in_review"){
     const [object_key,sha256,byte_length,approved_at,released_at,s]=args;
     this.report={session_id:s,object_key,sha256,byte_length,approved_at,released_at,revoked_at:null};changes=1;}
   }else if(sql.startsWith("UPDATE qira_intakes SET state='delivered'")){
    if(this.report&&this.order.state==="in_review"){this.order.state="delivered";changes=1;}
   }else if(sql.startsWith("INSERT INTO qira_operator_audit")){
    const [id,s,sub,actionDetail,created_at]=args;
    if(this.report&&this.order.state==="delivered"){this.actions.push({id,session_id:s,actor_sub:sub,action:"publish",detail:actionDetail,created_at});changes=1;}
   }else throw Error("unexpected batch "+sql.slice(0,80));
   results.push({success:true,meta:{changes}});
  }
  return results;
 }
}
class Store{
 constructor(){this.items=new Map();}
 async put(key,bytes){this.items.set(key,new Uint8Array(bytes));return {size:bytes.byteLength};}
 async delete(key){this.items.delete(key);}
}
const env=()=>({QIRA_PROOF_ORDERS:new DB(),QIRA_PROOF_REPORTS:new Store()});
const req=(path,body)=>new Request(host+path,{method:"POST",headers:{Origin:host},body});
const state=(action,attest="yes")=>req("/state",new URLSearchParams({session_id:sid,action,attest}));
const pdf=()=>new File([new TextEncoder().encode("%PDF-1.7\n"+("human review evidence\n").repeat(25)+"%%EOF\n")],"approved.pdf",{type:"application/pdf"});
const upload=({attest="yes",reference="Signed review: authority scope payment and source lines independently checked",filename=pdf()}={})=>{
 const f=new FormData();f.set("session_id",sid);f.set("attest",attest);f.set("reference",reference);f.set("report",filename);return req("/release",f);
};
test("operator desk refuses missing identity and reports no private content",async()=>{
 const e=env();
 const r=await handleOperatorRequest(new Request(host+"/"),e,null);
 assert.equal(r.status,401);
 assert.doesNotMatch(await r.text(),/buyer@example.invalid|Test\/repo/);
});
test("authorized operator must confirm authority before transitioning paid review",async()=>{
 const e=env();
 assert.equal((await handleOperatorRequest(state("authorize","no"),e,identity)).status,400);
 assert.equal(e.QIRA_PROOF_ORDERS.order.state,"awaiting_authorization");
 let r=await handleOperatorRequest(state("authorize"),e,identity);
 assert.equal(r.status,303);assert.equal(e.QIRA_PROOF_ORDERS.order.state,"authorized");
 r=await handleOperatorRequest(state("begin"),e,identity);
 assert.equal(r.status,303);assert.equal(e.QIRA_PROOF_ORDERS.order.state,"in_review");
 assert.equal(e.QIRA_PROOF_ORDERS.actions.length,2);
});
test("report publication is prohibited until verified review stage and paid status",async()=>{
 const e=env();
 let r=await handleOperatorRequest(upload(),e,identity);
 assert.equal(r.status,409);assert.equal(e.QIRA_PROOF_REPORTS.items.size,0);
 e.QIRA_PROOF_ORDERS.order.state="in_review";e.QIRA_PROOF_ORDERS.order.refund_amount=5000;
 r=await handleOperatorRequest(upload(),e,identity);
 assert.equal(r.status,409);assert.equal(e.QIRA_PROOF_REPORTS.items.size,0);
});
test("human-signed PDF writes immutable R2 object, digest, final stage and operator audit",async()=>{
 const e=env();e.QIRA_PROOF_ORDERS.order.state="in_review";
 const r=await handleOperatorRequest(upload(),e,identity);
 assert.equal(r.status,303);
 const d=e.QIRA_PROOF_ORDERS.report;
 assert.ok(d?.object_key.startsWith("reports/"+sid+"/"));assert.match(d.sha256,/^[0-9a-f]{64}$/);
 assert.equal(e.QIRA_PROOF_REPORTS.items.size,1);
 assert.equal(e.QIRA_PROOF_ORDERS.order.state,"delivered");
 assert.equal(e.QIRA_PROOF_ORDERS.actions.at(-1).action,"publish");
 const duplicate=await handleOperatorRequest(upload(),e,identity);
 assert.equal(duplicate.status,409);assert.equal(e.QIRA_PROOF_REPORTS.items.size,1);
});
test("operator can immediately revoke an approved report without exposing an R2 URL",async()=>{
 const e=env();e.QIRA_PROOF_ORDERS.order.state="in_review";
 await handleOperatorRequest(upload(),e,identity);
 const body=new URLSearchParams({session_id:sid,reason:"The source report requires a corrected release",attest:"yes"});
 const r=await handleOperatorRequest(req("/revoke",body),e,identity);
 assert.equal(r.status,303);assert.ok(e.QIRA_PROOF_ORDERS.report.revoked_at);
 assert.equal(e.QIRA_PROOF_ORDERS.actions.at(-1).action,"revoke");
});
test("private desk renders an accessible action interface with no client-side script",async()=>{
 const e=env();const r=await handleOperatorRequest(new Request(host+"/"),e,identity),html=await r.text();
 assert.equal(r.status,200);assert.match(html,/<h1>Review\. Approve\. Release\.<\/h1>/);
 assert.match(html,/type="file"/);assert.match(html,/Cloudflare Access/);
 assert.doesNotMatch(html,/<script|r2\.dev/);
 assert.match(r.headers.get("content-security-policy"),/script-src 'none'/);
});
