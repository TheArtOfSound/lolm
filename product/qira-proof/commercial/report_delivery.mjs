// Qira Proof private R2 deliverable retrieval.
// Every download requires a completed and unreversed $299 order, human-released
// report, matched checkout mailbox, short-lived code, and one-use DB claim.
// No public object listing, uploads or operator release endpoints exist.
import {buyerDigest} from "./payments.mjs";
const MAX_BODY=4096, MAX_REPORT=10485760, CODE_TTL=600, MAX_FAIL=5;
const FROM="Qira Proof Reports <reports@imagineqira.com>";
const SECURE={"content-type":"application/json; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","referrer-policy":"no-referrer","x-robots-tag":"noindex, nofollow","cross-origin-resource-policy":"same-origin"};
function json(body,status=200){return new Response(JSON.stringify(body),{status,headers:SECURE});}
function email(v){
 if(typeof v!=="string")return null;
 const s=v.trim().toLowerCase();
 return s.length>=5&&s.length<=254&&/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(s)?s:null;
}
function session(v){return typeof v==="string"&&/^cs_live_[A-Za-z0-9]{10,255}$/.test(v)?v:null;}
function safeHex(a,b){
 if(typeof a!=="string"||typeof b!=="string"||a.length!==b.length)return false;
 let diff=0;for(let i=0;i<a.length;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);
 return diff===0;
}
function hex(bytes){return Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,"0")).join("");}
function now(){return Math.floor(Date.now()/1000);}
async function codeDigest(secret,sid,value){
 if(typeof secret!=="string"||secret.length<32)throw Error("key_unavailable");
 const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
 return hex(await crypto.subtle.sign("HMAC",key,new TextEncoder().encode("qira-proof-download-code-v1:"+sid+":"+value)));
}
function secureCode(){
 const bytes=new Uint32Array(1);crypto.getRandomValues(bytes);
 return String(bytes[0]%100000000).padStart(8,"0");
}
async function inputFor(request){
 if(request.method!=="POST")throw Error("method");
 if(request.headers.get("origin")!==new URL(request.url).origin)throw Error("origin");
 if(!/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type")||""))throw Error("type");
 const size=Number(request.headers.get("content-length"));
 if(Number.isFinite(size)&&size>MAX_BODY)throw Error("size");
 const reader=request.body?.getReader();if(!reader)throw Error("body");
 const arr=[];let count=0;try{
  while(true){const {done,value}=await reader.read();if(done)break;count+=value.byteLength;
   if(count>MAX_BODY){await reader.cancel();throw Error("size");}arr.push(value);}
 }finally{reader.releaseLock();}
 const combined=new Uint8Array(count);let offset=0;
 for(const chunk of arr){combined.set(chunk,offset);offset+=chunk.length;}
 try{return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(combined));}catch{throw Error("json");}
}
async function eligible(db,sid){
 return db.prepare(`SELECT o.status,o.refund_amount,o.buyer_email_digest,i.contact_email,i.state,
 d.object_key,d.file_name,d.media_type,d.sha256,d.byte_length
 FROM qira_orders o JOIN qira_intakes i ON i.session_id=o.session_id
 JOIN qira_deliverables d ON d.session_id=o.session_id
 WHERE o.session_id=? AND d.revoked_at IS NULL AND d.released_at<=?`)
  .bind(sid,now()).first();
}
function correctOrder(row,digest,mail){
 return row?.status==="paid"&&Number(row.refund_amount||0)===0&&row?.state==="delivered"&&
 typeof row.buyer_email_digest==="string"&&safeHex(row.buyer_email_digest,digest)&&
 row.contact_email===mail;
}
function reportValid(row){
 return /^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,220}\.(?:pdf|html|json)$/.test(row?.object_key||"")&&
 ["application/pdf","text/html","application/json"].includes(row.media_type)&&
 /^[0-9a-f]{64}$/.test(row.sha256||"")&&
 Number.isSafeInteger(row.byte_length)&&row.byte_length>=1&&row.byte_length<=MAX_REPORT;
}
function filename(name){
 const v=typeof name==="string"?name.replace(/[^a-zA-Z0-9_.-]/g,"_").slice(0,96):"";
 return v&&v!=="."&&v!==".."&&!v.includes("..")?v:"qira-proof-report.bin";
}
async function confirmBuyer(env,sid,mail){
 const row=await eligible(env.QIRA_PROOF_ORDERS,sid);
 if(!row||!reportValid(row))return null;
 const digest=await buyerDigest(env.QIRA_ORDER_EMAIL_PEPPER,mail);
 return digest&&correctOrder(row,digest,mail)?row:null;
}
export async function requestReportCode(request,env,fetcher=fetch){
 let data;try{data=await inputFor(request);}catch{return json({error:"invalid_request"},400);}
 const sid=session(data?.session_id),mail=email(data?.email);
 if(!sid||!mail)return json({error:"invalid_request"},400);
 const generic=()=>json({received:true,message:"If an approved report is ready for this paid order, an access code will be sent to the checkout email."},202);
 if(!env.QIRA_PROOF_ORDERS||!env.QIRA_PROOF_REPORTS||!env.QIRA_ORDER_EMAIL_PEPPER||!env.QIRA_RESEND_API_KEY)return json({error:"service_unavailable"},503);
 try{
  const approved=await confirmBuyer(env,sid,mail);
  if(!approved)return generic(); // no paid status, email or report-availability oracle
  const object=await env.QIRA_PROOF_REPORTS.head(approved.object_key);
  if(!object||object.size!==approved.byte_length)return generic();
  const t=now(),window=Math.floor(t/3600),code=secureCode(),digest=await codeDigest(env.QIRA_ORDER_EMAIL_PEPPER,sid,code);
  const accepted=await env.QIRA_PROOF_ORDERS.prepare(`
   INSERT INTO qira_report_challenges(session_id,otp_digest,expires_at,sent_at,send_window,send_count,failed_count,consumed_at)
   VALUES(?,?,?,?,?,1,0,NULL)
   ON CONFLICT(session_id) DO UPDATE SET
   otp_digest=excluded.otp_digest,expires_at=excluded.expires_at,sent_at=excluded.sent_at,
   send_window=excluded.send_window,
   send_count=CASE WHEN qira_report_challenges.send_window=excluded.send_window THEN qira_report_challenges.send_count+1 ELSE 1 END,
   failed_count=0,consumed_at=NULL
   WHERE qira_report_challenges.sent_at<=? AND
    (qira_report_challenges.send_window<>excluded.send_window OR qira_report_challenges.send_count<3)
   RETURNING session_id`).bind(sid,digest,t+CODE_TTL,t,window,t-90).first();
  if(!accepted)return generic();
  const key=hex(await crypto.subtle.digest("SHA-256",new TextEncoder().encode("report-code:"+sid+":"+digest)));
  const response=await fetcher("https://api.resend.com/emails",{
   method:"POST",headers:{"Authorization":"Bearer "+env.QIRA_RESEND_API_KEY,"Content-Type":"application/json","Idempotency-Key":"qira-r2-"+key},
   body:JSON.stringify({from:FROM,to:[rowEmail(approved)],subject:"Your Qira Proof report access code",
    text:"Your Qira Proof report access code is: "+code+"\n\nIt expires in 10 minutes and works once. If you did not request it, you can ignore this message. Do not share the code.\n\nReturn to https://proof.imagineqira.com/report-access and enter the code in the secure form."})
  });
  if(!response.ok)return generic();
  const receipt=await response.json().catch(()=>null);
  if(typeof receipt?.id!=="string")return generic();
  return generic();
 }catch{return generic();}
}
function rowEmail(row){return row.contact_email;}
export async function downloadReport(request,env){
 let data;try{data=await inputFor(request);}catch{return json({error:"invalid_request"},400);}
 const sid=session(data?.session_id),mail=email(data?.email),code=data?.code;
 if(!sid||!mail||typeof code!=="string"||!/^[0-9]{8}$/.test(code))return json({error:"invalid_request"},400);
 if(!env.QIRA_PROOF_ORDERS||!env.QIRA_PROOF_REPORTS||!env.QIRA_ORDER_EMAIL_PEPPER)return json({error:"service_unavailable"},503);
 const reject=()=>json({error:"invalid_or_expired_code"},403);
 try{
  const row=await confirmBuyer(env,sid,mail);if(!row)return reject();
  const t=now();
  const ch=await env.QIRA_PROOF_ORDERS.prepare("SELECT otp_digest,expires_at,failed_count,consumed_at FROM qira_report_challenges WHERE session_id=?").bind(sid).first();
  if(!ch||ch.expires_at<t||ch.consumed_at!=null||ch.failed_count>=MAX_FAIL)return reject();
  const digest=await codeDigest(env.QIRA_ORDER_EMAIL_PEPPER,sid,code);
  if(!safeHex(digest,ch.otp_digest)){
   await env.QIRA_PROOF_ORDERS.prepare("UPDATE qira_report_challenges SET failed_count=MIN(5,failed_count+1) WHERE session_id=? AND consumed_at IS NULL AND expires_at>=?").bind(sid,t).run();
   return reject();
  }
  const object=await env.QIRA_PROOF_REPORTS.get(row.object_key);
  if(!object||object.size!==row.byte_length||object.size>MAX_REPORT)return json({error:"report_unavailable"},503);
  const bytes=await object.arrayBuffer();
  if(bytes.byteLength!==row.byte_length||!safeHex(hex(await crypto.subtle.digest("SHA-256",bytes)),row.sha256))
   return json({error:"report_unavailable"},503);
  // One atomic claim. No two requests can redeem the same code.
  const used=await env.QIRA_PROOF_ORDERS.prepare(`UPDATE qira_report_challenges SET consumed_at=?
   WHERE session_id=? AND otp_digest=? AND consumed_at IS NULL AND failed_count<? AND expires_at>=?
   RETURNING session_id`).bind(t,sid,digest,MAX_FAIL,t).first();
  if(!used)return reject();
  return new Response(bytes,{status:200,headers:{
   "content-type":"application/octet-stream",
   "content-length":String(bytes.byteLength),
   "content-disposition":'attachment; filename="'+filename(row.file_name)+'"',
   "x-qira-report-sha256":row.sha256,
   "cache-control":"no-store, private",
   "x-content-type-options":"nosniff",
   "cross-origin-resource-policy":"same-origin",
   "content-security-policy":"default-src 'none'; sandbox",
   "referrer-policy":"no-referrer",
   "x-robots-tag":"noindex, nofollow"
  }});
 }catch{return json({error:"report_unavailable"},503);}
}
export async function purgeReportChallenges(db,t=now()){
 const result=await db.prepare("DELETE FROM qira_report_challenges WHERE expires_at<?").bind(t-86400).run();
 if(result?.success===false)throw Error("report_code_cleanup_failed");
}
