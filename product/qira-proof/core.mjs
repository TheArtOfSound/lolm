/* QIRA Proof / deterministic, offline evidence checker.
 * Input is a bounded normalized snapshot, never credentials, log streams,
 * source code or a request to execute a network operation.
 */
export const SCHEMA="qira-proof/snapshot-v1";
const MAX_FACTS=150;
const SIGNALS=new Set(["runtime_ssh_keyscan","ssh_host_key_pinned",
 "worker_preview_enabled","worker_public_enabled","worker_privileged_bindings",
 "repo_branch_protection_verifiable","workflow_token_write_permission",
 "workflow_untrusted_pull_request"]);
export const MODES={ready:"observed",unknown:"not_verified"};
const checks=[
 {key:"ssh_host_trust",title:"Deployment SSH trust requires verification",
  category:"Deployment integrity",level:"review",
  description:"A deployment workflow appears to populate SSH known_hosts at runtime using ssh-keyscan. Without an independently trusted fingerprint, the first connection may trust an attacker-controlled host.",
  next:"Pin and verify the expected SSH host public-key fingerprint through a trusted channel. Require StrictHostKeyChecking=yes and re-read the committed workflow."},
 {key:"worker_preview_surface",title:"Public preview surface on a Worker with privileged integrations",
  category:"Cloud edge",level:"review",
  description:"This Worker has public preview URLs enabled and one or more privileged bindings. That warrants a review of authentication and preview-route exposure; it does not establish an unauthorized access path.",
  next:"Verify application authentication on both production and preview routes. If preview URLs are unnecessary, disable them and re-read the setting."},
 {key:"workflow_token_scope",title:"Write-capable workflow exposed to an untrusted PR trigger",
  category:"CI/CD authorization",level:"high",
  description:"The declared workflow combines write-level token permission with a pull-request context identified as untrusted. Validate executable steps, fork restrictions, and token availability before treating it as exploitable.",
  next:"Prefer read-only default tokens, isolate untrusted builds from credential-bearing jobs, and review trigger-specific permission boundaries."},
 {key:"branch_protection_visibility",title:"Branch protection could not be verified",
  category:"Evidence coverage",level:"unknown",
  description:"The configured integration did not provide evidence of branch-protection settings. This is a visibility gap, not proof that protections are disabled.",
  next:"Grant a scoped administrative metadata reader or inspect branch rules in GitHub, then rescan with an authoritative result."}
];
function plain(o){return o&&typeof o==="object"&&!Array.isArray(o)&&Object.getPrototypeOf(o)===Object.prototype}
function checkString(x,max=200){return typeof x==="string"&&x.length>0&&x.length<=max&&!/[\u0000-\u001f]/.test(x)}
function checkUrl(s){
 if(!checkString(s,1024))return false;
 try{const u=new URL(s);return u.protocol==="https:"&&!u.username&&!u.password&&!u.search&&!u.hash}
 catch{return false}
}
function checkDate(s){return checkString(s,40)&&!Number.isNaN(Date.parse(s))&&/Z$|[+-]\d\d:\d\d$/.test(s)}
export function normalizeSnapshot(raw){
 if(!plain(raw)||raw.schema!==SCHEMA||!Array.isArray(raw.facts)||raw.facts.length>MAX_FACTS||
 !checkDate(raw.captured_at))throw Error("Invalid QIRA snapshot envelope");
 const facts=[];
 const seen=new Set();
 for(const f of raw.facts){
  if(!plain(f)||Object.keys(f).some(k=>!["provider","asset","signal","value","source_url","observed_at"].includes(k))||
     !["github","cloudflare"].includes(f.provider)||!checkString(f.asset,180)||
     !SIGNALS.has(f.signal)||!(typeof f.value==="boolean"||f.value==="unknown")||
     !checkUrl(f.source_url)||!checkDate(f.observed_at))throw Error("Invalid or unsafe snapshot fact");
  if((f.signal.startsWith("worker_")&&f.provider!=="cloudflare")||
     (!f.signal.startsWith("worker_")&&f.provider!=="github"))throw Error("Signal/provider mismatch");
  const id=f.provider+"|"+f.asset+"|"+f.signal;
  if(seen.has(id))throw Error("Conflicting duplicate facts: "+f.signal);
  seen.add(id);
  facts.push({provider:f.provider,asset:f.asset,signal:f.signal,value:f.value,
              source_url:f.source_url,observed_at:f.observed_at});
 }
 if(facts.length===0)throw Error("Snapshot has no evidence facts");
 return {schema:SCHEMA,captured_at:raw.captured_at,facts:facts.sort((a,b)=>
  (a.provider+"|"+a.asset+"|"+a.signal).localeCompare(b.provider+"|"+b.asset+"|"+b.signal))};
}
function factsMap(snapshot){
 const out=new Map();
 for(const f of snapshot.facts){
  const key=f.provider+"|"+f.asset;
  if(!out.has(key))out.set(key,new Map());
  out.get(key).set(f.signal,f);
 }
 return out;
}
function emit(findings,asset,check,refs,requiredSignals){
 const info=checks.find(x=>x.key===check);
 if(!info)throw Error("Unknown rule");
 findings.push({id:asset.provider+"|"+asset.asset+"|"+check,provider:asset.provider,
  asset:asset.asset,check,category:info.category,level:info.level,
  title:info.title,interpretation:info.description,next:info.next,
  confidence:info.level==="unknown"?"unverified":"configuration-observed/risk-conditional",
  evidence:refs.map(f=>({signal:f.signal,observed_value:f.value,
   observed_at:f.observed_at,source_url:f.source_url})),
  required_signals:requiredSignals});
}
export function analyzeSnapshot(input){
 const snapshot=normalizeSnapshot(input), groups=factsMap(snapshot),findings=[];
 for(const [id,observations] of groups){
  const [provider,...rest]=id.split("|"), asset={provider,asset:rest.join("|")};
  const yes=x=>observations.get(x)?.value===true;
  const no=x=>observations.get(x)?.value===false;
  const f=x=>observations.get(x);
  if(provider==="github"){
   if(yes("runtime_ssh_keyscan")&&!yes("ssh_host_key_pinned")){
    emit(findings,asset,"ssh_host_trust",[f("runtime_ssh_keyscan"),...(f("ssh_host_key_pinned")?[f("ssh_host_key_pinned")]:[])],
      ["runtime_ssh_keyscan","ssh_host_key_pinned"]);
   }
   if(yes("workflow_token_write_permission")&&yes("workflow_untrusted_pull_request")){
    emit(findings,asset,"workflow_token_scope",[f("workflow_token_write_permission"),f("workflow_untrusted_pull_request")],
      ["workflow_token_write_permission","workflow_untrusted_pull_request"]);
   }
   if(f("repo_branch_protection_verifiable")?.value==="unknown"){
    emit(findings,asset,"branch_protection_visibility",[f("repo_branch_protection_verifiable")],
      ["repo_branch_protection_verifiable"]);
   }
  }
  if(provider==="cloudflare"&&yes("worker_preview_enabled")&&yes("worker_privileged_bindings")){
    emit(findings,asset,"worker_preview_surface",[f("worker_preview_enabled"),f("worker_privileged_bindings"),...(f("worker_public_enabled")?[f("worker_public_enabled")]:[])],
      ["worker_preview_enabled","worker_privileged_bindings"]);
  }
 }
 const severity={high:0,review:1,unknown:2};
 findings.sort((a,b)=>severity[a.level]-severity[b.level]||a.id.localeCompare(b.id));
 return {schema:"qira-proof/assessment-v1",snapshot_at:snapshot.captured_at,assets:groups.size,
   facts:snapshot.facts.length,findings,
   counts:{high:findings.filter(x=>x.level==="high").length,
           review:findings.filter(x=>x.level==="review").length,
           unknown:findings.filter(x=>x.level==="unknown").length},
   conclusion:"Configuration review candidates. Not confirmed compromises, exploitable vulnerabilities, or causal effectiveness."};
}
export function compareSnapshots(beforeInput,afterInput){
 const before=normalizeSnapshot(beforeInput),after=normalizeSnapshot(afterInput);
 const oldReport=analyzeSnapshot(before),newReport=analyzeSnapshot(after);
 const nextMap=new Map(after.facts.map(x=>[x.provider+"|"+x.asset+"|"+x.signal,x]));
 const nextIds=new Set(newReport.findings.map(x=>x.id));
 const deltas=[];
 for(const item of oldReport.findings){
  const complete=item.required_signals.every(sig=>nextMap.has(item.provider+"|"+item.asset+"|"+sig));
  // The SSH known-host case permits an authoritative positive pin even when
  // the original ssh-keyscan line remains. Missing pin = unknown, not fixed.
  const explicitSSH=item.check==="ssh_host_trust"&&nextMap.get(item.provider+"|"+item.asset+"|ssh_host_key_pinned")?.value===true;
  const rechecked=complete||explicitSSH;
  deltas.push({id:item.id,title:item.title,
   state:!rechecked?"not-rechecked":nextIds.has(item.id)?"still-observed":"indicator-cleared",
   explanation:!rechecked?"Required facts missing from follow-up evidence":
    nextIds.has(item.id)?"Same configuration condition remains":
    "The supplied follow-up facts no longer trigger this rule; not proof of security or prevention"});
 }
 const initial=new Set(oldReport.findings.map(x=>x.id));
 for(const n of newReport.findings)if(!initial.has(n.id))
  deltas.push({id:n.id,title:n.title,state:"newly-observed",explanation:"New finding in follow-up snapshot"});
 return {schema:"qira-proof/comparison-v1",baseline_at:before.captured_at,followup_at:after.captured_at,
  deltas,verified_changes:0,conclusion:"Comparison checks evidence indicators only; actual remediation effectiveness is unverified."};
}
export function canonical(o){
 if(Array.isArray(o))return "["+o.map(canonical).join(",")+"]";
 if(o&&typeof o==="object")return "{"+Object.keys(o).sort().map(k=>JSON.stringify(k)+":"+canonical(o[k])).join(",")+"}";
 return JSON.stringify(o);
}
export async function sha256(s){
 const buf=new TextEncoder().encode(s);
 const digest=await globalThis.crypto.subtle.digest("SHA-256",buf);
 return Array.from(new Uint8Array(digest)).map(x=>x.toString(16).padStart(2,"0")).join("");
}
export async function proof(snapshot,followup=null){
 const baseline=normalizeSnapshot(snapshot),after=followup?normalizeSnapshot(followup):null;
 const assessment=analyzeSnapshot(baseline),comparison=after?compareSnapshots(baseline,after):null;
 const payload={schema:"qira-proof/evidence-v1",baseline,after,assessment,comparison,
  attestation:"self-contained deterministic calculation, NOT source authentication, a signature, or proof of prevention"};
 return {...payload,sha256:await sha256(canonical(payload))};
}
export async function verifyProof(doc){
 if(!plain(doc)||doc.schema!=="qira-proof/evidence-v1"||typeof doc.sha256!=="string")return false;
 try{
  const fresh=await proof(doc.baseline,doc.after);
  return canonical(fresh)===canonical(doc);
 }catch{return false}
}
