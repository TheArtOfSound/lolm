/* QIRA Proof: static, printable human report from a deterministic evidence receipt.
 * Client only, no network requests, no third-party fonts/scripts, no tracking.
 * Do not turn a SHA-256 integrity receipt into a claim of provider authentication.
 */
import {verifyProof,groupReviewFindings} from "./core.mjs";

const escapeHTML=value=>String(value??"").replace(/[&<>"']/g,c=>({
 "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
}[c]));
const nice=value=>escapeHTML(value);
function safeHref(value){
 try{
  const u=new URL(value);
  return u.protocol==="https:"&&!u.username&&!u.password&&!u.search&&!u.hash?
   escapeHTML(u.href):null;
 }catch{return null;}
}
function timestamp(value){
 const ms=Date.parse(value);
 return Number.isFinite(ms)?escapeHTML(new Date(ms).toISOString()):"Invalid timestamp";
}
function findingView(item,index){
 const severity=item.level==="high"?"Elevated / verify":item.level==="review"?"Review":"Not verified";
 const observations=item.evidence.map(f=>{
  const href=safeHref(f.source_url),value=nice(f.observed_value);
  const source=href?`<a href="${href}" rel="noreferrer noopener" target="_blank">Declared evidence location</a>`:"Unverifiable source link";
  const file=typeof f.asset==="string"&&f.asset.includes(":.github/workflows/")?
   f.asset.split(":.github/workflows/")[1]+" · ":"";
  return `<li><b>${nice(file+f.signal)}</b>: ${value}<small>Observed ${timestamp(f.observed_at)} · ${source}</small></li>`;
 }).join("");
 return `<article class="finding"><header><span class="num">${String(index+1).padStart(2,"0")}</span>
  <div><h3>${nice(item.title)}</h3><p class="meta">${nice(item.provider)} / ${nice(item.asset)} · ${nice(item.category)}</p></div>
  <span class="pill">${escapeHTML(severity)}</span></header>
  <p>${nice(item.interpretation)}</p>
  <h4>Recommended verification</h4><p>${nice(item.next)}</p>
  <h4>Observed evidence</h4><ul>${observations}</ul></article>`;
}
function coverageView(facts){
 const providers=[...new Set(facts.map(x=>x.provider))].sort();
 return providers.map(p=>{
  const subset=facts.filter(x=>x.provider===p);
  const assets=new Set(subset.map(x=>x.asset)).size;
  return `<div class="coverage"><b>${nice(p.toUpperCase())}</b><strong>${assets}</strong>
    <span>${assets===1?"asset":"assets"} · ${subset.length} facts</span></div>`;
 }).join("");
}
function repositoryCoverageView(coverage){
 if(!coverage)return '<p class="muted">No repository-wide workflow coverage record was supplied. This report may represent only one file or a limited set of evidence facts.</p>';
 const n=coverage;
 return `<div class="disclaimer"><b>Repository scan coverage — ${n.complete?"all discovered workflows inspected":"PARTIAL"}</b>
  <p>${n.assessed} of ${n.discovered} workflows assessed; ${n.skipped} failed or skipped.
  ${n.truncated?"At least some workflows were outside the 20-file scan limit.":"No additional workflows were excluded by the scan limit."}</p>
  <p>Bounded review at source commit <code>${nice(n.commit)}</code> for <b>${nice(n.repository)}</b>. 
  This summary is included in the verifiable evidence JSON, but does not prove complete repository security coverage.</p></div>`;
}
function comparisonView(comparison){
 if(!comparison)return '<p class="muted">No authorized follow-up snapshot supplied. Remediation was not assessed.</p>';
 return `<p class="muted">Recheck: ${timestamp(comparison.followup_at)}. This compares indicators only, not security effectiveness.</p>`+
  (comparison.deltas.length?'<table><thead><tr><th>Review item</th><th>Indicator state</th></tr></thead><tbody>'+
    comparison.deltas.map(d=>`<tr><td>${nice(d.title)}</td><td>${nice(d.state)}<small>${nice(d.explanation)}</small></td></tr>`).join("")+
    '</tbody></table>':'<p>No baseline review conditions needed a follow-up comparison.</p>');
}
/**
 * Render only after local receipt verification. The output is a standalone
 * static HTML document that users can print or save as PDF in their browser.
 * No finding is described as a confirmed breach or certified remediation.
 */
export async function renderHumanReport(receipt,{sample=false}={}){
 if(!receipt||typeof receipt!=="object"||!(await verifyProof(receipt)))
  throw Error("Evidence receipt failed deterministic verification");
 const {assessment,baseline,comparison,sha256}=receipt;
 const heading=sample?"FICTIONAL EXAMPLE — NOT A CUSTOMER ASSESSMENT":"Owner-supplied / connected configuration evidence";
 const visibleFindings=baseline.coverage?groupReviewFindings(assessment.findings):assessment.findings;
 const findings=visibleFindings.length?visibleFindings.map(findingView).join(""):
  '<div class="empty">No configured Qira rule matched these facts. This is not a clean bill of health.</div>';
 return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
 <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'; base-uri 'none'">
 <meta name="referrer" content="no-referrer"><title>Qira Proof | Configuration review${sample?" — fictional example":""}</title>
 <style>
 :root{color-scheme:light}*{box-sizing:border-box}body{font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;color:#16282c;margin:0;background:#edf2ef}
 main{max-width:900px;background:#fff;margin:36px auto;padding:48px 56px;box-shadow:0 16px 70px #263e361a}
 .eyebrow{text-transform:uppercase;letter-spacing:.13em;color:#496757;font-size:11px;font-weight:800}
 h1{font-size:40px;letter-spacing:-.045em;line-height:1.14;margin:10px 0 8px}
 h2{font-size:20px;letter-spacing:-.02em;border-bottom:1px solid #d7e3dc;padding-bottom:10px;margin-top:34px}
 h3{font-size:17px;line-height:1.3;margin:0}h4{font-size:12px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
 p{margin:9px 0}.meta,.muted{color:#576e70;font-size:13px}
 .disclaimer{border-left:3px solid #8b9866;background:#f4f6ec;padding:15px 18px;margin:24px 0;font-size:13px}
 .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:26px 0}
 .stat,.coverage{border:1px solid #dbe4df;border-radius:10px;padding:13px}
 .stat b,.coverage b{display:block;font-size:11px;color:#4b6867;text-transform:uppercase}
 .stat strong,.coverage strong{display:block;font-size:26px;margin-top:4px;font-variant-numeric:tabular-nums}
 .coverage{display:inline-block;vertical-align:top;min-width:160px;margin-right:8px}.coverage span{display:block;color:#576e70;font-size:11px}
 .finding{border-top:1px solid #dae3dd;padding:21px 0;break-inside:avoid-page}
 .finding header{display:flex;align-items:flex-start;gap:13px}.finding header>div{flex:1}
 .num{font-weight:800;color:#5c7d68}.pill{font-size:11px;color:#344b52;background:#eaf1ed;padding:5px 9px;border-radius:40px;white-space:nowrap}
 ul{padding-left:22px}li{margin-bottom:7px;overflow-wrap:anywhere}small{display:block;color:#647778}a{color:#244baa}
 table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:10px;text-align:left;border-bottom:1px solid #dce5de;vertical-align:top}
 code{overflow-wrap:anywhere;font-size:11px}.hash{border:1px solid #dce5de;background:#f7f9f7;padding:12px;border-radius:8px}
 .empty{padding:16px;background:#f7f9f6;color:#52656a}
 footer{border-top:1px solid #d9e3dc;padding-top:15px;margin-top:38px;font-size:11px;color:#657879}
 @media print{body{background:#fff}main{margin:0;max-width:none;padding:0;box-shadow:none}a{text-decoration:none;color:#16282c}.finding{break-inside:avoid-page}h2{break-after:avoid-page}}
 @media(max-width:650px){main{margin:0;padding:24px 18px}.stats{grid-template-columns:repeat(2,1fr)}h1{font-size:30px}.finding header{flex-wrap:wrap}}
 </style></head><body><main>
 <div class="eyebrow">QIRA Proof / Read-only configuration review</div>
 <h1>Infrastructure configuration assessment</h1>
 <p class="meta">${escapeHTML(heading)}<br>Evidence captured: ${timestamp(baseline.captured_at)}</p>
 <div class="disclaimer"><b>Scope and assurance limits:</b> This document evaluates only supplied or temporarily retrieved configuration facts. It does not prove provider identity, full coverage, exploitability, or absence of vulnerabilities. It is not a penetration test or security certification. SHA-256 provides alteration detection, not a digital signature.</div>
 <div class="stats"><div class="stat"><b>Assets represented</b><strong>${assessment.assets}</strong></div>
 <div class="stat"><b>Evidence facts</b><strong>${assessment.facts}</strong></div>
 <div class="stat"><b>Review observations</b><strong>${assessment.counts.high+assessment.counts.review}</strong></div>
 <div class="stat"><b>Visibility gaps</b><strong>${assessment.counts.unknown}</strong></div></div>
 <h2>Scope of evidence</h2><div>${coverageView(baseline.facts)}</div>
 ${repositoryCoverageView(baseline.coverage)}
 <p class="muted">Some providers may have been omitted. Facts from different cloud services are not automatically linked to a single application.</p>
 <h2>Observations and recommended verification</h2>${findings}
 <h2>Follow-up comparison</h2>${comparisonView(comparison)}
 <h2>Evidence receipt</h2><p>Reproduce this review using the companion JSON evidence receipt. The hash is only meaningful when verified against that JSON.</p>
 <div class="hash"><code>SHA-256: ${escapeHTML(sha256)}</code></div>
 <footer>Qira Proof · Owner-supplied / connected observations · Not a provider-signed attestation · No automatic infrastructure changes. ${sample?"Fictional demonstration only.":""}</footer>
 </main></body></html>`;
}
