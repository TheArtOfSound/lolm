import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto,createHash} from "node:crypto";
import {buyerDigest} from "../commercial/payments.mjs";
import {requestReportCode,downloadReport,purgeReportChallenges} from "../commercial/report_delivery.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const sid="cs_live_qiraV14Safe1234567890",mail="buyer@example.invalid",pepper="local_only_0123456789abcdef0123456789abcdef_012345",api="https://proof.imagineqira.com";
const bytes=new TextEncoder().encode("%PDF-1.4\nQira verified sample only\n%%EOF");
const digest=createHash("sha256").update(bytes).digest("hex"),objectKey="reports/test-order/approved.pdf";
function request(path,body,origin=api){return new Request(api+path,{method:"POST",headers:{"Content-Type":"application/json",Origin:origin},body:JSON.stringify(body)});}
class R2{
 constructor(){this.data=new Map([[objectKey,bytes]]);}
 async head(key){const data=this.data.get(key);return data?{size:data.byteLength}:null;}
 async get(key){const data=this.data.get(key);return data?{size:data.byteLength,arrayBuffer:async()=>data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength)}:null;}
}
class Ledger{
 constructor(){this.deliverable={session_id:sid,object_key:objectKey,file_name:"qira-proof-assessment.pdf",media_type:"application/pdf",sha256:digest,byte_length:bytes.length,revoked_at:null,released_at:Math.floor(Date.now()/1000)-60};
 this.order={status:"paid",refund_amount:0,buyer_email_digest:null};this.intake={contact_email:mail,state:"delivered"};this.challenge=null;}
 prepare(sql){const db=this;return {bind(...args){return {sql,args,
 async first(){
  const now=Math.floor(Date.now()/1000);
  if(sql.includes("FROM qira_orders o JOIN qira_intakes i")){
   if(args[0]!==sid||db.deliverable.revoked_at!==null||db.deliverable.released_at>args[1])return null;
   return {...db.order,...db.intake,...db.deliverable};
  }
  if(sql.includes("INSERT INTO qira_report_challenges")){
   const [sess,otp,expire,sent,window,cutoff]=args;if(sess!==sid)return null;
   if(db.challenge&&!(db.challenge.sent_at<=cutoff&&(db.challenge.send_window!==window||db.challenge.send_count<3)))return null;
   const count=db.challenge?.send_window===window?db.challenge.send_count+1:1;
   db.challenge={session_id:sid,otp_digest:otp,expires_at:expire,sent_at:sent,send_window:window,send_count:count,failed_count:0,consumed_at:null};return {session_id:sid};
  }
  if(sql.includes("SELECT otp_digest,expires_at"))return args[0]===sid?db.challenge:null;
  if(sql.includes("UPDATE qira_report_challenges SET consumed_at")){
   const [at,sess,token,max,stamp]=args;
   if(sess!==sid||!db.challenge||db.challenge.otp_digest!==token||db.challenge.consumed_at!==null||db.challenge.failed_count>=max||db.challenge.expires_at<stamp)return null;
   db.challenge.consumed_at=at;return {session_id:sid};
  }
  throw Error("unexpected first "+sql.slice(0,100));
 },
 async run(){
  if(sql.includes("SET failed_count=MIN")){
   if(db.challenge&&db.challenge.consumed_at==null&&db.challenge.expires_at>=args[1])db.challenge.failed_count=Math.min(5,db.challenge.failed_count+1);
   return {success:true};
  }
  if(sql.startsWith("DELETE FROM qira_report_challenges")){
   if(db.challenge&&db.challenge.expires_at<args[0])db.challenge=null;return {success:true};
  }
  throw Error("unexpected run "+sql.slice(0,100));
 }
 };}};}
}
async function setup(){
 const db=new Ledger();db.order.buyer_email_digest=await buyerDigest(pepper,mail);
 return {db,r2:new R2(),env:{QIRA_PROOF_ORDERS:db,QIRA_PROOF_REPORTS:new R2(),QIRA_ORDER_EMAIL_PEPPER:pepper,QIRA_RESEND_API_KEY:"re_mock_not_for_delivery"}};
}
async function otp(env,db,m=mail){
 const calls=[],fetcher=async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>({id:"11111111-2222-4333-8444-555555555555"})};};
 const response=await requestReportCode(request("/api/reports/request-code",{session_id:sid,email:m}),env,fetcher);
 const sent=calls[0]?JSON.parse(calls[0].opts.body):null;
 const code=sent?.text.match(/access code is: (\d{8})/)?.[1];
 return {response,calls,code};
}
test("an unsigned checkout reference or mismatched buyer never produces a code",async()=>{
 const {db,env}=await setup();db.order.status="pending";
 let out=await otp(env,db);assert.equal(out.response.status,202);assert.equal(out.calls.length,0);
 db.order.status="paid";
 out=await otp(env,db,"intruder@example.invalid");assert.equal(out.response.status,202);assert.equal(out.calls.length,0);
 db.intake.state="awaiting_authorization";
 out=await otp(env,db);assert.equal(out.calls.length,0);
 db.intake.state="delivered";db.deliverable.revoked_at=Math.floor(Date.now()/1000);
 out=await otp(env,db);assert.equal(out.calls.length,0);
});
test("a genuine released, paid, mailbox-matched report permits one verified download",async()=>{
 const {db,env}=await setup();const issued=await otp(env,db);
 assert.equal(issued.response.status,202);assert.equal(issued.calls.length,1);
 assert.match(issued.code,/^\d{8}$/);
 const result=await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:issued.code}),env);
 assert.equal(result.status,200);
 assert.equal(result.headers.get("content-type"),"application/octet-stream");
 assert.match(result.headers.get("content-disposition"),/attachment;/);
 assert.equal(result.headers.get("x-qira-report-sha256"),digest);
 assert.equal(await result.text(),new TextDecoder().decode(bytes));
 const replay=await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:issued.code}),env);
 assert.equal(replay.status,403);
});
test("wrong code, lockout and code expiry all block private bytes",async()=>{
 const {db,env}=await setup();const sent=await otp(env,db);
 for(let i=0;i<5;i++)assert.equal((await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:"99999999"===sent.code?"88888888":"99999999"}),env)).status,403);
 assert.equal(db.challenge.failed_count,5);
 assert.equal((await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:sent.code}),env)).status,403);
 db.challenge.failed_count=0;db.challenge.expires_at=0;
 assert.equal((await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:sent.code}),env)).status,403);
});
test("partial refunds, corrupted files, and missing files never release bytes",async()=>{
 const {db,env}=await setup();const issued=await otp(env,db);
 db.order.refund_amount=5000;
 assert.equal((await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:issued.code}),env)).status,403);
 db.order.refund_amount=0;
 env.QIRA_PROOF_REPORTS.data.set(objectKey,new TextEncoder().encode("changed without approval"));
 assert.equal((await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:issued.code}),env)).status,503);
 assert.equal(db.challenge.consumed_at,null);
 env.QIRA_PROOF_REPORTS.data.delete(objectKey);
 assert.equal((await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:issued.code}),env)).status,503);
});
test("code issuance cannot flood an inbox, and cross-origin submissions fail",async()=>{
 const {db,env}=await setup();
 const first=await otp(env,db);assert.equal(first.calls.length,1);
 const second=await otp(env,db);assert.equal(second.calls.length,0);
 const x=await requestReportCode(request("/api/reports/request-code",{session_id:sid,email:mail},"https://attacker.invalid"),env,async()=>{throw Error("bad")});
 assert.equal(x.status,400);
 const badly=await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:"12345678"},"https://attacker.invalid"),env);
 assert.equal(badly.status,400);
});
test("a missing secure R2 binding fails closed; retention purges only expired codes",async()=>{
 const {db,env}=await setup();delete env.QIRA_PROOF_REPORTS;
 const response=await requestReportCode(request("/api/reports/request-code",{session_id:sid,email:mail}),env,async()=>{throw Error("must not call")});
 assert.equal(response.status,503);
 const denied=await downloadReport(request("/api/reports/download",{session_id:sid,email:mail,code:"12345678"}),env);
 assert.equal(denied.status,503);
 const old=Math.floor(Date.now()/1000);db.challenge={expires_at:old-90000};
 await purgeReportChallenges(db,old);assert.equal(db.challenge,null);
});
