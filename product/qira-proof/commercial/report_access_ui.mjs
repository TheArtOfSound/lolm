// V14, standalone report retrieval. No client tokens or download grants in URLs.
export const REPORT_ACCESS_CSS=String.raw`
.ra-page{background:#fafbf9;color:#203a31;min-height:63vh}
.ra-wrap{width:min(1120px,calc(100% - 40px));margin:auto}
.ra-hero{background:#eef2ec;border-bottom:1px solid #ccd9ce;padding:58px 0 45px}
.ra-kicker{font:700 11px/1.4 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.12em;color:#82503d}
.ra-hero h1{font:400 clamp(46px,5.2vw,74px)/1.08 Georgia,serif;letter-spacing:-.05em;max-width:780px;margin:16px 0 19px;color:#203a31}
.ra-hero p{font:440 17px/1.65 system-ui,sans-serif;color:#506c5f;max-width:680px;margin:0}
.ra-hero-tags{display:flex;flex-wrap:wrap;gap:18px;margin-top:27px;color:#456353;font:650 11px/1.4 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.035em}
.ra-hero-tags span{display:inline-flex;align-items:center;gap:8px}
.ra-hero-tags span:before{content:"";width:6px;height:6px;border:1px solid #588369;border-radius:100%}
.ra-workspace{display:grid;grid-template-columns:minmax(0,1.14fr) minmax(260px,.7fr);gap:48px;padding:43px 0 80px;align-items:start}
.ra-panel{background:#fff;border:1px solid #cbd8cc;box-shadow:0 24px 55px #1e4a300d}
.ra-panel-head{background:#f3f7f2;border-bottom:1px solid #d9e3d9;display:flex;justify-content:space-between;align-items:center;gap:12px;padding:16px 24px}
.ra-panel-head strong,.ra-panel-head span{font:680 11px/1.4 ui-monospace,monospace;letter-spacing:.05em;text-transform:uppercase}
.ra-panel-head span{color:#6a8977}
.ra-body{padding:30px 32px 34px}
.ra-body h2{font:400 32px/1.15 Georgia,serif;letter-spacing:-.03em;margin:0 0 8px}
.ra-body>p{font:450 13px/1.65 system-ui,sans-serif;color:#627a6c;margin:0 0 27px}
.ra-field{display:grid;gap:8px;margin:0 0 19px}
.ra-field label{font:650 12px/1.5 system-ui,sans-serif;color:#365447}
.ra-field input{width:100%;max-width:100%;border:1px solid #bdcec0;background:#fff;border-radius:3px;padding:13px 14px;font:450 14px/1.4 ui-monospace,monospace;color:#203a31}
.ra-field input:focus-visible{outline:3px solid #94b5a1;outline-offset:2px}
.ra-field small{font:450 11px/1.55 system-ui,sans-serif;color:#61796b}
.ra-primary{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:15px 16px;color:#fff;background:#263f34;border:1px solid #263f34;border-radius:3px;font:650 13px/1.4 system-ui,sans-serif}
.ra-primary:hover{background:#3e604c}.ra-primary:disabled{opacity:.55;cursor:wait}
.ra-status{font:550 12px/1.65 system-ui,sans-serif;color:#42634d;margin:14px 0 0;min-height:20px}
.ra-step{padding-top:22px;margin-top:25px;border-top:1px solid #dbe5dc}
.ra-step[hidden]{display:none}
.ra-rule{border-top:1px solid #cfdbd0;padding:19px 0}
.ra-rule:first-child{border-top:0;padding-top:4px}
.ra-rule>span{font:700 11px ui-monospace,monospace;color:#a45c44}
.ra-rule h3{font:600 14px/1.5 system-ui,sans-serif;margin:7px 0;color:#2f4f3b}
.ra-rule p{font:440 12px/1.72 system-ui,sans-serif;margin:0;color:#607868}
.ra-aside h2{font:400 25px/1.3 Georgia,serif;letter-spacing:-.025em;margin:2px 0 15px}
.ra-aside>a{color:#345d49;font:620 12px system-ui,sans-serif;text-underline-offset:3px}
.ra-note{margin-top:24px;padding:15px 18px;background:#edf4ed;border-left:3px solid #739a7c;color:#41614e;font:440 12px/1.6 system-ui,sans-serif}
@media(max-width:790px){.ra-workspace{grid-template-columns:1fr;gap:27px;padding-top:23px}.ra-hero{padding:40px 0}.ra-body{padding:23px 20px}.ra-panel-head{padding:14px 20px}.ra-wrap{width:min(1120px,calc(100% - 32px))}.ra-hero h1{font-size:45px}.ra-hero p{font-size:15px}.ra-aside{order:2}}
@media(prefers-reduced-motion:reduce){.ra-page *{animation:none!important;transition:none!important}}
`;
export function renderReportAccess(){return String.raw`<section class="ra-page">
<header class="ra-hero"><div class="ra-wrap"><div class="ra-kicker">Qira Proof / Secure fulfillment</div><h1>A finished review belongs in your hands.</h1><p>Retrieve a human-approved report securely. We verify your original checkout email, send a one-time code, and release only the exact report attached to your order.</p>
<div class="ra-hero-tags"><span>Private file storage</span><span>One-time verification</span><span>Checked document integrity</span></div></div></header>
<div class="ra-wrap ra-workspace"><section class="ra-panel" aria-labelledby="raTitle"><div class="ra-panel-head"><strong>Secure report access</strong><span>01 / Verification</span></div><div class="ra-body"><h2 id="raTitle">Access your assessment</h2><p>This works after the review is complete and the final document has been approved. No additional payment is required.</p>
<form id="raRequest" novalidate>
<div class="ra-field"><label for="raSession">Stripe checkout session reference</label><input id="raSession" name="session_id" autocomplete="off" spellcheck="false" required placeholder="cs_live_…" maxlength="263" pattern="cs_live_[A-Za-z0-9]{10,255}"><small>Find this in your Qira Proof checkout return link. Keep it private.</small></div>
<div class="ra-field"><label for="raEmail">Email used at checkout</label><input id="raEmail" name="email" type="email" autocomplete="email" required maxlength="254" placeholder="you@company.com"></div>
<button class="ra-primary" type="submit"><span>Request a one-time access code</span><span aria-hidden="true">→</span></button><p id="raRequestStatus" class="ra-status" role="status" aria-live="polite"></p></form>
<div class="ra-step" id="raConfirm" hidden><form id="raDownload" novalidate><div class="ra-field"><label for="raCode">Eight-digit email code</label><input id="raCode" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{8}" maxlength="8" required placeholder="00000000"><small>Valid for 10 minutes and one download. Enter the code from the checkout mailbox.</small></div><button class="ra-primary" type="submit"><span>Verify and download the report</span><span aria-hidden="true">↓</span></button><p id="raDownloadStatus" class="ra-status" role="status" aria-live="polite"></p></form></div>
</div></section>
<aside class="ra-aside" aria-labelledby="raRules"><h2 id="raRules">How we protect the handoff</h2>
<div class="ra-rule"><span>01 / AUTHORIZATION</span><h3>Payment is not repository permission</h3><p>We release reports only after the original transaction, authorized source access and a completed human review are confirmed.</p></div>
<div class="ra-rule"><span>02 / IDENTITY</span><h3>The checkout inbox is the key</h3><p>Knowing a checkout reference alone does not unlock a report. The short-lived code goes only to the verified purchase email.</p></div>
<div class="ra-rule"><span>03 / INTEGRITY</span><h3>Exactly what was approved</h3><p>Each document is checked against its recorded SHA-256 before download. A mismatch blocks delivery.</p></div>
<div class="ra-rule"><span>04 / SUPPORT</span><h3>Still waiting on your report?</h3><p>If your review is not complete, no code is sent. Please do not make another purchase.</p></div>
<a href="mailto:bryanleonard@imagineqira.com?subject=Qira%20Proof%20report%20access">Contact report support</a><div class="ra-note">Codes are never included in URL parameters. The private bucket has no public file listing or public download domain.</div>
</aside></div></section>`;}
export const REPORT_ACCESS_SCRIPT=String.raw`<script>
(function(){
 const ask=document.getElementById('raRequest'),get=document.getElementById('raDownload');
 const requestStatus=document.getElementById('raRequestStatus'),downloadStatus=document.getElementById('raDownloadStatus');
 const codePanel=document.getElementById('raConfirm');
 if(!ask||!get||!requestStatus||!downloadStatus||!codePanel)return;
 const params=new URLSearchParams(location.search),prefill=params.get('session_id');
 if(prefill&&/^cs_live_[A-Za-z0-9]{10,255}$/.test(prefill))document.getElementById('raSession').value=prefill;
 async function post(path,body){return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',credentials:'same-origin',body:JSON.stringify(body)});}
 function values(){return {session_id:document.getElementById('raSession').value.trim(),email:document.getElementById('raEmail').value.trim()};}
 function valid(v){return /^cs_live_[A-Za-z0-9]{10,255}$/.test(v.session_id)&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email);}
 function busy(form,on){const b=form.querySelector('button[type="submit"]');if(b)b.disabled=on;}
 ask.addEventListener('submit',async e=>{e.preventDefault();const v=values();if(!valid(v)){requestStatus.textContent='Enter your full Stripe checkout session and the original checkout email.';return;}
  busy(ask,true);requestStatus.textContent='Checking the release record…';
  try{const r=await post('/api/reports/request-code',v);if(r.status===202){requestStatus.textContent='If an approved report is ready for this order, an access code will be sent to your checkout email. Check your inbox.';codePanel.hidden=false;}else requestStatus.textContent='We could not process this request. Try again or contact report support.';}
  catch{requestStatus.textContent='The service could not be reached. Your order has not been changed.';}finally{busy(ask,false);}
 });
 get.addEventListener('submit',async e=>{e.preventDefault();const v=values(),code=document.getElementById('raCode').value.trim();if(!valid(v)||!/^[0-9]{8}$/.test(code)){downloadStatus.textContent='Enter the valid eight-digit code and keep your checkout details unchanged.';return;}
  busy(get,true);downloadStatus.textContent='Verifying the one-time code and document integrity…';
  try{const r=await post('/api/reports/download',{...v,code});if(!r.ok){downloadStatus.textContent=r.status===403?'That code was not accepted. Check the email code, its expiry and your checkout details.':'The report is temporarily unavailable. Contact Qira support; do not pay again.';return;}
   const blob=await r.blob(),hash=r.headers.get('x-qira-report-sha256'),disposition=r.headers.get('content-disposition')||'',filename=(disposition.match(/filename="([^"]+)"/)||[])[1]||'qira-proof-report.bin';
   const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
   downloadStatus.textContent='Report download initiated. Your single-use code is now consumed.'+(hash?' Integrity reference (SHA-256): '+hash:'');document.getElementById('raCode').value='';
  }catch{downloadStatus.textContent='We could not complete the download. Contact Qira support rather than paying again.';}finally{busy(get,false);}
 });
})();
</script>`;
