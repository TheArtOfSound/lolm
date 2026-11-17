// Qira Proof operator desk. Separate Cloudflare Access-protected Worker.
// Fail-closed even if the Access app/route is misconfigured: every request
// requires a cryptographically verified Cloudflare Access JWT for this app
// audience and exact owner email. Never enable a workers.dev public route.
const HOST="ops.proof.imagineqira.com";
const ACCESS_ISSUER="https://autohustle.cloudflareaccess.com";
const MAX_REPORT=10*1024*1024, MAX_MULTIPART=MAX_REPORT+25000;
const jsonHeaders={"content-type":"application/json; charset=utf-8","cache-control":"no-store, private","x-content-type-options":"nosniff","x-frame-options":"DENY","referrer-policy":"no-referrer","x-robots-tag":"noindex,nofollow","cross-origin-resource-policy":"same-origin"};
const htmlHeaders={...jsonHeaders,"content-type":"text/html; charset=utf-8","content-security-policy":"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; script-src 'none'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'; connect-src 'none'"};
const now=()=>Math.floor(Date.now()/1000);
function respond(data,status=200){return new Response(JSON.stringify(data),{status,headers:jsonHeaders});}
function escape(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function base64Url(s){const t=s.replace(/-/g,"+").replace(/_/g,"/");const raw=atob(t+"=".repeat((4-t.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));}
function decode(token){const p=token.split(".");if(p.length!==3)return null;try{const h=JSON.parse(new TextDecoder().decode(base64Url(p[0]))),c=JSON.parse(new TextDecoder().decode(base64Url(p[1])));return {parts:p,header:h,claims:c};}catch{return null;}}
let certsCache={until:0,keys:null};
export async function verifyOperator(request,env,fetcher=fetch){
 let u;try{u=new URL(request.url);}catch{return null;}
 if(u.protocol!=="https:"||u.hostname!==HOST)return null;
 const audience=env?.QIRA_PROOF_OPS_AUD,owner=env?.QIRA_PROOF_OPS_EMAIL;
 if(typeof audience!=="string"||!/^[-a-f0-9]{40,128}$/i.test(audience)||typeof owner!=="string"||owner.length<5)return null;
 const token=request.headers.get("cf-access-jwt-assertion");
 if(typeof token!=="string"||token.length<100||token.length>10000||!/^[A-Za-z0-9_.-]+$/.test(token))return null;
 const decoded=decode(token);if(!decoded)return null;
 const {parts,header,claims}=decoded;
 const t=now();
 if(header.alg!=="RS256"||typeof header.kid!=="string"||header.kid.length<3||header.kid.length>200)return null;
 if(claims.iss!==ACCESS_ISSUER||
    !(Array.isArray(claims.aud)?claims.aud.includes(audience):claims.aud===audience)||
    typeof claims.email!=="string"||claims.email.toLowerCase()!==owner.toLowerCase()||
    typeof claims.sub!=="string"||claims.sub.length<10||claims.sub.length>256||
    !Number.isInteger(claims.exp)||claims.exp<=t||claims.exp>t+86400||
    !Number.isInteger(claims.iat)||claims.iat>t+60||claims.iat<t-86400||
    (claims.nbf!=null&&claims.nbf>t+60))return null;
 try{
  let keys;
  if(fetcher===fetch&&certsCache.keys&&certsCache.until>t)keys=certsCache.keys;
  else{
   const resp=await fetcher(ACCESS_ISSUER+"/cdn-cgi/access/certs",{method:"GET",headers:{"Accept":"application/json"},redirect:"error"});
   if(!resp.ok)return null;
   const c=await resp.json();
   if(!Array.isArray(c.keys)||c.keys.length>32)return null;
   keys=c.keys.filter(k=>k.kty==="RSA"&&k.kid&&k.n&&k.e);
   if(fetcher===fetch)certsCache={keys,until:t+300};
  }
  const candidate=keys.find(k=>k.kid===header.kid);
  if(!candidate)return null;
  const key=await crypto.subtle.importKey("jwk",candidate,{name:"RSASSA-PKCS1-v1_5",hash:"SHA-256"},false,["verify"]);
  const authentic=await crypto.subtle.verify("RSASSA-PKCS1-v1_5",key,base64Url(parts[2]),new TextEncoder().encode(parts[0]+"."+parts[1]));
  return authentic?{sub:claims.sub,email:claims.email}:null;
 }catch{return null;}
}
function safeSession(s){return typeof s==="string"&&/^cs_live_[A-Za-z0-9]{10,255}$/.test(s)?s:null;}
function ref(s){return String(s??"").trim().slice(0,400);}
function redirect(status){return new Response(null,{status:303,headers:{location:"/?status="+encodeURIComponent(status),"cache-control":"no-store","referrer-policy":"no-referrer"}});}
function postOrigin(request){return request.headers.get("origin")==="https://"+HOST&&request.headers.get("sec-fetch-site")!=="cross-site";}
async function formSmall(request){
 if(!postOrigin(request))throw Error("origin");
 if(!/^application\/x-www-form-urlencoded(?:;|$)/i.test(request.headers.get("content-type")||""))throw Error("media");
 const body=await request.text();if(body.length>4096)throw Error("body");
 return new URLSearchParams(body);
}
async function formFile(request){
 if(!postOrigin(request))throw Error("origin");
 if(!/^multipart\/form-data;\s*boundary=/i.test(request.headers.get("content-type")||""))throw Error("media");
 const announced=Number(request.headers.get("content-length"));
 if(Number.isFinite(announced)&&announced>MAX_MULTIPART)throw Error("size");
 const reader=request.body?.getReader();if(!reader)throw Error("body");
 const pieces=[];let total=0;
 try{while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;
  if(total>MAX_MULTIPART){await reader.cancel();throw Error("size");}pieces.push(value);}}finally{reader.releaseLock();}
 const bytes=new Uint8Array(total);let off=0;for(const p of pieces){bytes.set(p,off);off+=p.byteLength;}
 const form=await new Response(bytes,{headers:{"content-type":request.headers.get("content-type")}}).formData();
 return form;
}
async function order(db,sid){
 return db.prepare("SELECT o.session_id,o.status,o.refund_amount,i.state,i.repository,i.contact_email FROM qira_orders o JOIN qira_intakes i ON i.session_id=o.session_id WHERE o.session_id=?").bind(sid).first();
}
const paid=o=>o?.status==="paid"&&Number(o.refund_amount||0)===0;
async function audit(db,sid,actor,action,detail){
 const actorId=actor?.sub;
 if(typeof actorId!=="string"||actorId.length<10)throw Error("actor_missing");
 const entry=await db.prepare("INSERT INTO qira_operator_audit(id,session_id,actor_sub,action,detail,created_at) VALUES(?,?,?,?,?,?)").bind(crypto.randomUUID(),sid,actorId,action,detail,now()).run();
 if(entry?.success===false)throw Error("audit_failed");
}
function badge(value){
 const map={paid:"Paid",refunded:"Refunded",disputed:"Disputed",pending:"Pending",failed:"Failed",authorized:"Authorized",in_review:"In review",delivered:"Delivered",cancelled:"Cancelled",awaiting_authorization:"Needs authorization"};
 return escape(map[value]||value);
}
function page(rows,audits,status){
 const cards=(rows||[]).map(r=>`<article class="order">
 <div class="order-head"><div><small>CHECKOUT SESSION</small><code>${escape(r.session_id)}</code></div><div class="tags"><span>${badge(r.status)}</span><span>${badge(r.state)}</span></div></div>
 <div class="order-body"><dl><div><dt>Selected repository</dt><dd>${escape(r.repository)}</dd></div><div><dt>Checkout contact</dt><dd>${escape(r.contact_email)}</dd></div><div><dt>Refund amount</dt><dd>${Number(r.refund_amount||0)/100} USD</dd></div><div><dt>Document</dt><dd>${r.object_key?"Released · "+escape(r.sha256?.slice(0,16))+"…":"Not released"}</dd></div></dl>
 ${r.state==="awaiting_authorization"&&paid(r)?`<form method="POST" action="/state"><input type="hidden" name="session_id" value="${escape(r.session_id)}"><input type="hidden" name="action" value="authorize"><label><input type="checkbox" name="attest" value="yes" required> I personally verified owner/delegated authority for this repository.</label><button type="submit">Record authorization</button></form>`:""}
 ${r.state==="authorized"&&paid(r)?`<form method="POST" action="/state"><input type="hidden" name="session_id" value="${escape(r.session_id)}"><input type="hidden" name="action" value="begin"><label><input type="checkbox" name="attest" value="yes" required> I verified the agreed scope and read-only repository access.</label><button type="submit">Begin review</button></form>`:""}
 ${r.object_key&&!r.revoked_at?`<form method="POST" action="/revoke"><input type="hidden" name="session_id" value="${escape(r.session_id)}"><label for="reason-${escape(r.session_id)}">Revocation reason</label><input id="reason-${escape(r.session_id)}" name="reason" minlength="12" maxlength="240" required placeholder="Reason and case reference"><label><input type="checkbox" name="attest" value="yes" required> I understand this blocks new report downloads.</label><button class="danger" type="submit">Revoke report access</button></form>`:""}
 </div></article>`).join("");
 const events=(audits||[]).map(x=>`<tr><td>${escape(x.action)}</td><td><code>${escape(x.session_id)}</code></td><td>${escape(x.detail)}</td><td>${escape(new Date(Number(x.created_at)*1000).toISOString().slice(0,16).replace("T"," "))} UTC</td></tr>`).join("");
 return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Operator desk | Qira Proof</title>
 <style>:root{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1d322d;background:#f7f8f5}*{box-sizing:border-box}body{margin:0}header{background:#162d26;color:#e6f1e8;border-bottom:4px solid #9bbb95}header>div,main,footer{max-width:1160px;margin:auto;padding-left:24px;padding-right:24px}header>div{display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:76px}.brand{font-size:18px;font-weight:760;letter-spacing:-.04em}.brand small{font:500 11px ui-monospace,monospace;color:#b0cebd;padding-left:12px;letter-spacing:.02em}header p{font-size:12px;color:#b6cebc}h1{font:400 clamp(42px,6vw,64px)/1.06 Georgia,serif;letter-spacing:-.05em;margin:24px 0 15px}main{padding-top:22px;padding-bottom:70px}.lead{max-width:770px;color:#61756a;font-size:15px;line-height:1.75}.aside{padding:16px 20px;border-left:3px solid #9fb597;background:#eaf0e8;color:#466451;font-size:12px;line-height:1.75;margin:24px 0}.section-head{display:flex;justify-content:space-between;align-items:baseline;gap:20px;margin:45px 0 15px}.section-head h2{font:400 31px Georgia,serif;margin:0;letter-spacing:-.035em}.section-head span{font:600 11px ui-monospace,monospace;color:#6c8478}.orders{display:grid;gap:14px}.order,.upload{border:1px solid #d1ddd3;background:#fff}.order-head{display:flex;justify-content:space-between;gap:18px;padding:17px 20px;background:#eff4ef;border-bottom:1px solid #dbe5db}.order-head small{display:block;font:700 10px ui-monospace,monospace;color:#61816d;margin-bottom:5px}.order-head code{overflow-wrap:anywhere;font:550 12px ui-monospace,monospace;color:#2c4939}.tags{display:flex;align-items:start;gap:6px;flex-wrap:wrap}.tags span{font:700 10px ui-monospace,monospace;padding:5px 8px;border:1px solid #adc9b4;color:#386349}.order-body{padding:19px 20px}.order dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:0}.order dt{font-size:11px;color:#718779;margin-bottom:4px}.order dd{font-size:13px;margin:0;overflow-wrap:anywhere}.order form{margin-top:22px;padding-top:17px;border-top:1px solid #e3eae3}.order label, .upload label{display:block;font-size:12px;color:#3b5b48;line-height:1.6;margin:10px 0}.order label:has(input[type=checkbox]),.upload label:has(input[type=checkbox]){display:flex;align-items:start;gap:9px}.order input[type=checkbox],.upload input[type=checkbox]{margin-top:4px}.order input:not([type=checkbox]),.upload input:not([type=checkbox]){width:100%;padding:12px;border:1px solid #bccfc0;background:#fff;border-radius:2px;color:#19382b;font:500 13px system-ui}.order button,.upload button{margin-top:12px;background:#254639;border:0;color:#fff;font:650 12px system-ui;padding:12px 18px;cursor:pointer;border-radius:2px}.order button:hover,.upload button:hover{background:#3c6250}.order button.danger{background:#7a3f32}.upload{padding:24px}.upload p{font-size:12px;line-height:1.75;color:#667c6c}.upload code{background:#edf3ed;padding:2px 4px}table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #d1ddd3}td,th{text-align:left;padding:12px;border-bottom:1px solid #e0e8df;font-size:12px;overflow-wrap:anywhere}th{font:700 11px ui-monospace,monospace;color:#536e5c;background:#f0f4f0}.status{padding:12px 16px;background:#e9f0e9;border:1px solid #d2ded2;font-size:13px;color:#385847}footer{padding:23px 24px 35px;color:#7b8a7f;font-size:11px;border-top:1px solid #dce7dd}@media(max-width:650px){.order-head{display:block}.tags{margin-top:12px}.order dl{grid-template-columns:1fr}.section-head{display:block}.upload{padding:18px}header p{display:none}h1{font-size:43px}table{display:block;overflow-x:auto}}</style></head>
 <body><header><div><div class="brand">QIRA / PROOF <small>OPERATIONS</small></div><p>Cloudflare Access · Owner-restricted</p></div></header><main><h1>Review. Approve. Release.</h1><p class="lead">Private fulfillment desk for paid GitHub Actions reviews. Every action here requires an authenticated Cloudflare Access identity. Payment alone is not repository authorization; publication is a deliberate human signoff.</p>
 <div class="aside"><strong>Before changing a customer record:</strong> check the exact Stripe payment and refund/dispute state directly in Trend, independently confirm customer authority and read-only GitHub scope, inspect the reviewed document, and confirm promised delivery timing. No action here substitutes for those checks.</div>
 ${status?`<p class="status" role="status">${escape(status)}</p>`:""}
 <div class="section-head"><h2>Paid review queue</h2><span>${rows?.length||0} MOST RECENT REQUESTS</span></div>
 <div class="orders">${cards||'<p>No customer reviews have been submitted. New verified orders appear here after paid intake.</p>'}</div>
 <div class="section-head"><h2>Publish an approved report</h2><span>PDF · MAX 10 MIB</span></div>
 <form class="upload" method="POST" action="/release" enctype="multipart/form-data"><p>Upload a final <strong>human-verified</strong> PDF. The Worker checks the signed payment ledger, scope state, file size, PDF signature and SHA-256, then writes a new immutable private R2 key and the D1 release record. The verified customer receives an email through the scheduled outbox.</p>
 <label for="releaseSession">Verified Stripe Checkout Session</label><input id="releaseSession" name="session_id" required pattern="cs_live_[A-Za-z0-9]{10,255}" placeholder="cs_live_…">
 <label for="releaseFile">Approved PDF assessment</label><input id="releaseFile" type="file" name="report" accept="application/pdf,.pdf" required>
 <label for="releaseNote">Review and approval reference (20–400 characters)</label><input id="releaseNote" name="reference" required minlength="20" maxlength="400" placeholder="Scope confirmed, source references checked, reviewed by…">
 <label><input type="checkbox" name="attest" value="yes" required> I have personally verified the buyer's authority, current Stripe status, scope, findings, document integrity and human approval.</label>
 <button type="submit">Publish approved PDF to private R2</button></form>
 <div class="section-head"><h2>Recent operator actions</h2><span>AUDIT TRAIL</span></div>
 <table><thead><tr><th>Action</th><th>Checkout</th><th>Reference</th><th>UTC</th></tr></thead><tbody>${events||'<tr><td colspan="4">No operator actions recorded.</td></tr>'}</tbody></table>
 </main><footer>Private desk. Do not share links, customer identifiers, reports, credentials or checkout data publicly.</footer></body></html>`;
}
async function queue(db){
 const q=await db.prepare(`SELECT o.session_id,o.status,o.refund_amount,i.state,i.repository,i.contact_email,
 d.object_key,d.sha256,d.revoked_at
 FROM qira_intakes i JOIN qira_orders o ON o.session_id=i.session_id
 LEFT JOIN qira_deliverables d ON d.session_id=i.session_id
 ORDER BY i.submitted_at DESC LIMIT 40`).all();
 const audit=await db.prepare("SELECT session_id,action,detail,created_at FROM qira_operator_audit ORDER BY created_at DESC LIMIT 20").all();
 if(q?.success===false||audit?.success===false)throw Error("read_error");
 return {orders:q.results||[],audits:audit.results||[]};
}
async function changeState(request,env,actor){
 let body;try{body=await formSmall(request);}catch{return respond({error:"invalid_request"},400);}
 const sid=safeSession(body.get("session_id")),action=body.get("action");
 if(!sid||body.get("attest")!=="yes"||!["authorize","begin"].includes(action))return respond({error:"invalid_request"},400);
 const old=action==="authorize"?"awaiting_authorization":"authorized",next=action==="authorize"?"authorized":"in_review";
 try{
  const current=await order(env.QIRA_PROOF_ORDERS,sid);
  if(!paid(current)||current.state!==old)return redirect("Payment or review state is not eligible. Check Stripe and scope.");
  const r=await env.QIRA_PROOF_ORDERS.prepare(`UPDATE qira_intakes SET state=?
   WHERE session_id=? AND state=? AND EXISTS(
   SELECT 1 FROM qira_orders o WHERE o.session_id=qira_intakes.session_id AND o.status='paid' AND COALESCE(o.refund_amount,0)=0)
   RETURNING session_id`).bind(next,sid,old).first();
  if(!r)return redirect("Review state changed; reload before trying again.");
  await audit(env.QIRA_PROOF_ORDERS,sid,actor,action,"Human authorization/scope attestation");
  return redirect(action==="authorize"?"Repository authority recorded.":"Review marked in progress.");
 }catch{return respond({error:"state_change_unavailable"},503);}
}
async function publish(request,env,actor){
 let body;try{body=await formFile(request);}catch{return respond({error:"invalid_upload_or_too_large"},413);}
 const sid=safeSession(body.get("session_id")),note=ref(body.get("reference")),file=body.get("report");
 if(!sid||body.get("attest")!=="yes"||note.length<20||note.length>400||!(file instanceof File)||file.size<128||file.size>MAX_REPORT||!file.name.toLowerCase().endsWith(".pdf"))
  return respond({error:"invalid_report_or_attestation"},400);
 try{
  const db=env.QIRA_PROOF_ORDERS,store=env.QIRA_PROOF_REPORTS;
  const current=await order(db,sid);
  if(!paid(current)||current.state!=="in_review")return respond({error:"review_not_eligible"},409);
  const existing=await db.prepare("SELECT session_id FROM qira_deliverables WHERE session_id=?").bind(sid).first();
  if(existing)return respond({error:"report_already_exists"},409);
  const bytes=await file.arrayBuffer();if(bytes.byteLength!==file.size)return respond({error:"size_mismatch"},400);
  const data=new Uint8Array(bytes);
  if(new TextDecoder().decode(data.slice(0,5))!=="%PDF-"||
     !new TextDecoder().decode(data.slice(-1024)).includes("%%EOF"))
   return respond({error:"pdf_signature_invalid"},400);
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),b=>b.toString(16).padStart(2,"0")).join("");
  const objectKey="reports/"+sid+"/"+crypto.randomUUID()+".pdf";
  const r2=await store.put(objectKey,bytes,{httpMetadata:{contentType:"application/octet-stream",cacheControl:"private, no-store"},customMetadata:{sha256:digest}});
  if(!r2||r2.size!==bytes.byteLength)throw Error("r2_put_failed");
  const t=now();
  try{
   const committed=await db.batch([
    db.prepare(`INSERT INTO qira_deliverables(session_id,object_key,file_name,media_type,sha256,byte_length,approved_at,released_at,revoked_at)
     SELECT o.session_id,?,'qira-proof-approved-report.pdf','application/pdf',?,?,?,?,NULL
     FROM qira_orders o JOIN qira_intakes i ON i.session_id=o.session_id
     WHERE o.session_id=? AND o.status='paid' AND COALESCE(o.refund_amount,0)=0
     AND i.state='in_review' AND NOT EXISTS(SELECT 1 FROM qira_deliverables d WHERE d.session_id=o.session_id)`)
      .bind(objectKey,digest,bytes.byteLength,t,t,sid),
    db.prepare(`UPDATE qira_intakes SET state='delivered'
     WHERE session_id=? AND state='in_review' AND EXISTS(
     SELECT 1 FROM qira_deliverables d WHERE d.session_id=qira_intakes.session_id AND d.object_key=?)`).bind(sid,objectKey),
    db.prepare(`INSERT INTO qira_operator_audit(id,session_id,actor_sub,action,detail,created_at)
     SELECT ?,? ,?,'publish',?,?
     WHERE EXISTS(SELECT 1 FROM qira_deliverables d JOIN qira_intakes i ON d.session_id=i.session_id
     WHERE d.session_id=? AND d.object_key=? AND i.state='delivered')`)
      .bind(crypto.randomUUID(),sid,actor.sub,note+" | SHA256 "+digest,t,sid,objectKey)
   ]);
   if(!Array.isArray(committed)||committed.length!==3||committed.some(q=>q?.success===false||Number(q?.meta?.changes)!==1))throw Error("report_db_commit_failed");
  }catch(e){
   // D1 batch is transactional on statements with SQL errors, but a logically
   // rejected conditional INSERT can change zero rows without failing. If the
   // release is not fully committed, revoke the partial record before cleanup.
   await db.prepare("UPDATE qira_deliverables SET revoked_at=? WHERE session_id=? AND object_key=?").bind(now(),sid,objectKey).run().catch(()=>{});
   await store.delete(objectKey).catch(()=>{});
   throw e;
  }
  return redirect("Approved report released to R2. The scheduled queue will notify the buyer.");
 }catch{return respond({error:"report_release_unavailable"},503);}
}
async function revoke(request,env,actor){
 let b;try{b=await formSmall(request);}catch{return respond({error:"invalid_request"},400);}
 const sid=safeSession(b.get("session_id")),reason=ref(b.get("reason"));
 if(!sid||reason.length<12||reason.length>240||b.get("attest")!=="yes")return respond({error:"invalid_request"},400);
 try{
  const n=await env.QIRA_PROOF_ORDERS.prepare("UPDATE qira_deliverables SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL RETURNING session_id").bind(now(),sid).first();
  if(!n)return redirect("No currently released report was found.");
  await audit(env.QIRA_PROOF_ORDERS,sid,actor,"revoke",reason);
  return redirect("Report access revoked. Existing downloaded copies cannot be retracted.");
 }catch{return respond({error:"revoke_unavailable"},503);}
}
export default {async fetch(request,env){
 const identity=await verifyOperator(request,env);
 if(!identity)return respond({error:"operator_access_denied"},401);
 if(!env?.QIRA_PROOF_ORDERS||!env?.QIRA_PROOF_REPORTS)return respond({error:"operator_bindings_unavailable"},503);
 const path=new URL(request.url).pathname;
 if(request.method==="GET"&&path==="/"){
  try{const {orders,audits}=await queue(env.QIRA_PROOF_ORDERS);
   const notice=new URL(request.url).searchParams.get("status")?.slice(0,180);
   return new Response(page(orders,audits,notice),{headers:htmlHeaders});
  }catch{return respond({error:"operator_queue_unavailable"},503);}
 }
 if(request.method==="POST"&&path==="/state")return changeState(request,env,identity);
 if(request.method==="POST"&&path==="/release")return publish(request,env,identity);
 if(request.method==="POST"&&path==="/revoke")return revoke(request,env,identity);
 return respond({error:"not_found"},404);
}};
