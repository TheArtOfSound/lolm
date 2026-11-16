/* QIRA Proof / deterministic, offline evidence checker.
 * Input is a bounded normalized snapshot, never credentials, log streams,
 * source code or a request to execute a network operation.
 */
export const SCHEMA="qira-proof/snapshot-v1";
const MAX_FACTS=150;
const SIGNALS=new Set(["runtime_ssh_keyscan","ssh_host_key_pinned",
 "worker_preview_enabled","worker_public_enabled","worker_privileged_bindings",
 "repo_branch_protection_verifiable","workflow_unpinned_actions","workflow_token_write_permission",
 "workflow_explicit_read_only_permissions","workflow_pull_request_target_trigger",
 "workflow_untrusted_pull_request","vercel_recent_preview_observed",
 "vercel_deployment_protection_configured","vercel_latest_production_errored"]);
export const MODES={ready:"observed",unknown:"not_verified"};
const checks=[
 {key:"workflow_action_integrity",title:"Third-party CI actions use mutable version references",
  category:"Build supply-chain integrity",level:"review",
  description:"One or more non-local GitHub Actions in the selected workflow use a tag or branch rather than a complete 40-character commit SHA. These references can change over time. This is a hardening opportunity, not proof of a malicious update.",
  next:"Inspect each external uses: reference in the selected workflow and pin its reviewed full commit SHA. Maintain a controlled update process for those pins."},
 {key:"privileged_pr_trigger",title:"Write permissions and pull_request_target declared together",
  category:"CI/CD authorization",level:"review",
  description:"This workflow declares a write-level permission and a pull_request_target trigger. Their coexistence warrants examining what code the workflow checks out and executes; the trigger by itself is not a vulnerability.",
  next:"Inspect checkout ref and commands executed by pull_request_target jobs; do not execute untrusted fork code in a secret-bearing context. Check current GitHub Actions event policies and job-level token overrides."},
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
 {key:"vercel_preview_visibility",title:"Recent preview deployment without verified project-level protection",
  category:"Deployment access",level:"review",
  description:"The supplied Vercel metadata shows a recent preview deployment, while the three reported project-level deployment protection methods are disabled. This does not establish that the preview is publicly reachable or sensitive.",
  next:"Confirm intended preview visibility, inspect Vercel's Deployment Protection scope, and test access without a session only with the owner's authorization."},
 {key:"vercel_production_release",title:"Latest production deployment reports an error",
  category:"Release reliability",level:"review",
  description:"The most recent observed production-target deployment has ERROR status. An older deployment may still be serving traffic; this is not evidence of an outage.",
  next:"Inspect the failed deployment in Vercel, verify the currently promoted production version, and check release protections before attempting a retry."},
 {key:"branch_protection_visibility",title:"Branch protection could not be verified",
  category:"Evidence coverage",level:"unknown",
  description:"The configured integration did not provide evidence of branch-protection settings. This is a visibility gap, not proof that protections are disabled.",
  next:"Grant a scoped administrative metadata reader or inspect branch rules in GitHub, then rescan with an authoritative result."}
];
function plain(o){return o&&typeof o==="object"&&!Array.isArray(o)&&Object.getPrototypeOf(o)===Object.prototype}
function checkString(x,max=200){return typeof x==="string"&&x.length>0&&x.length<=max&&!/[\u0000-\u001f]/.test(x)}
function checkUrl(s){
 if(!checkString(s,1024))return false;
 try{
  const u=new URL(s);
  const permittedAnchor=!u.hash||(
   u.hostname==="github.com"&&/^#L[1-9][0-9]{0,5}$/.test(u.hash)&&
   /^\/[^/?#]+\/[^/?#]+\/blob\/[a-fA-F0-9]{40}\/\.github\/workflows\/[^?#]+$/.test(u.pathname));
  return u.protocol==="https:"&&!u.username&&!u.password&&!u.search&&permittedAnchor;
 }
 catch{return false}
}
function checkDate(s){return checkString(s,40)&&!Number.isNaN(Date.parse(s))&&/Z$|[+-]\d\d:\d\d$/.test(s)}
// Coverage belongs inside the SHA-256 receipt, not only an ephemeral UI banner.
// This is a scope record, not attestation that the scan was security-complete.
function normalizeCoverage(v){
 const keys=["mode","repository","discovered","selected","assessed","skipped","limit",
             "complete","truncated","commit"];
 if(!plain(v)||Object.keys(v).length!==keys.length||Object.keys(v).some(k=>!keys.includes(k))||
    v.mode!=="bounded-repository-workflows"||!checkString(v.repository,180)||
    !/^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/.test(v.repository)||
    !/^[a-fA-F0-9]{40}$/.test(v.commit)||v.limit!==20||
    ![v.discovered,v.selected,v.assessed,v.skipped].every(Number.isSafeInteger)||
    v.discovered<1||v.discovered>100||v.selected<1||v.selected>20||
    v.selected>v.discovered||v.assessed<1||v.skipped<0||v.assessed+v.skipped!==v.selected||
    typeof v.complete!=="boolean"||typeof v.truncated!=="boolean"||
    v.complete!==(!v.truncated&&v.discovered===v.selected&&v.skipped===0)||
    (!v.truncated&&v.discovered>v.selected))
  throw Error("Invalid QIRA repository coverage summary");
 return {mode:v.mode,repository:v.repository,discovered:v.discovered,selected:v.selected,
  assessed:v.assessed,skipped:v.skipped,limit:v.limit,complete:v.complete,
  truncated:v.truncated,commit:v.commit.toLowerCase()};
}
// A bounded provider-declared scope inventory. Each entry is a recognized
// permission name, with an immutable source line. This is source evidence,
// not verification of effective GitHub token permissions.
const WRITABLE_SCOPES=new Set(["actions","artifact-metadata","attestations","checks",
 "code-quality","contents","copilot-requests","deployments","discussions",
 "id-token","issues","packages","pages","pull-requests","security-events",
 "statuses","write-all"]);
function normalizePermissionInventory(entries,facts){
 if(!Array.isArray(entries)||entries.length===0||entries.length>20)
  throw Error("Invalid bounded permission inventory");
 const known=new Set(),normalized=[];
 for(const item of entries){
  if(!plain(item)||Object.keys(item).length!==2||
     !Object.hasOwn(item,"asset")||!Object.hasOwn(item,"scopes")||
     !checkString(item.asset,180)||!Array.isArray(item.scopes)||
     item.scopes.length===0||item.scopes.length>36||known.has(item.asset))
   throw Error("Invalid permission inventory entry");
  known.add(item.asset);
  const observed=facts.find(f=>f.provider==="github"&&f.asset===item.asset&&
    f.signal==="workflow_token_write_permission"&&f.value===true);
  if(!observed)throw Error("Permission inventory has no matching write observation");
  const [repo,workflow]=item.asset.split(":.github/workflows/");
  const repository=repo;
  if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository))
   throw Error("Permission inventory repository invalid");
  const canonicalRoot="https://github.com/"+repository+"/blob/";
  const unique=new Set(),scopes=[];
  for(const entry of item.scopes){
   if(!plain(entry)||Object.keys(entry).length!==2||
      !WRITABLE_SCOPES.has(entry.scope)||!checkUrl(entry.source_url)||
      !/^#L[1-9][0-9]{0,5}$/.test(new URL(entry.source_url).hash)||
      !entry.source_url.startsWith(canonicalRoot))
    throw Error("Invalid permission inventory scope or source");
   const parsed=new URL(entry.source_url),segments=parsed.pathname.split("/");
   if(!/^[a-fA-F0-9]{40}$/.test(segments[4]||"")||
      !parsed.pathname.includes("/.github/workflows/"))
    throw Error("Permission inventory source not commit pinned");
   const observedUrl=new URL(observed.source_url);
   if(parsed.pathname!==observedUrl.pathname)
    throw Error("Permission inventory workflow mismatch");
   if(workflow&&parsed.pathname!=="/"+repository+"/blob/"+segments[4]+"/.github/workflows/"+workflow)
    throw Error("Permission inventory asset mismatch");
   const key=entry.scope+"|"+entry.source_url;
   if(unique.has(key))throw Error("Duplicate permission inventory declaration");
   unique.add(key);scopes.push({scope:entry.scope,source_url:entry.source_url});
  }
  scopes.sort((a,b)=>(a.scope+"|"+a.source_url).localeCompare(b.scope+"|"+b.source_url));
  normalized.push({asset:item.asset,scopes});
 }
 normalized.sort((a,b)=>a.asset.localeCompare(b.asset));
 return normalized;
}
export function normalizeSnapshot(raw){
 if(!plain(raw)||raw.schema!==SCHEMA||!Array.isArray(raw.facts)||raw.facts.length>MAX_FACTS||
 !checkDate(raw.captured_at))throw Error("Invalid QIRA snapshot envelope");
 const facts=[];
 const seen=new Set();
 for(const f of raw.facts){
  if(!plain(f)||Object.keys(f).some(k=>!["provider","asset","signal","value","source_url","observed_at"].includes(k))||
     !["github","cloudflare","vercel"].includes(f.provider)||!checkString(f.asset,180)||
     !SIGNALS.has(f.signal)||!(typeof f.value==="boolean"||f.value==="unknown")||
     !checkUrl(f.source_url)||!checkDate(f.observed_at))throw Error("Invalid or unsafe snapshot fact");
  const prefix=f.signal.startsWith("worker_")?"cloudflare":
   f.signal.startsWith("vercel_")?"vercel":"github";
  if(f.provider!==prefix)throw Error("Signal/provider mismatch");
  const id=f.provider+"|"+f.asset+"|"+f.signal;
  if(seen.has(id))throw Error("Conflicting duplicate facts: "+f.signal);
  seen.add(id);
  facts.push({provider:f.provider,asset:f.asset,signal:f.signal,value:f.value,
              source_url:f.source_url,observed_at:f.observed_at});
 }
 if(facts.length===0)throw Error("Snapshot has no evidence facts");
 const normalized={schema:SCHEMA,captured_at:raw.captured_at,facts:facts.sort((a,b)=>
  (a.provider+"|"+a.asset+"|"+a.signal).localeCompare(b.provider+"|"+b.asset+"|"+b.signal))};
 if(raw.coverage!==undefined){
  normalized.coverage=normalizeCoverage(raw.coverage);
  if(!normalized.facts.some(f=>f.provider==="github"&&f.asset===normalized.coverage.repository&&
     f.signal==="repo_branch_protection_verifiable"))
   throw Error("Repository coverage missing its base evidence scope");
  if(normalized.facts.filter(f=>f.provider==="github"&&
     f.signal==="workflow_unpinned_actions"&&f.asset.startsWith(normalized.coverage.repository+":")).length
     !==normalized.coverage.assessed)
   throw Error("Repository coverage does not match observed workflow facts");
 }
 if(raw.permission_inventory!==undefined){
  normalized.permission_inventory=normalizePermissionInventory(raw.permission_inventory,normalized.facts);
 }
 return normalized;
}
export function mergeSnapshots(...inputs){
 // Explicitly combine separately authorized browser-local evidence.
 // Reject stale joins; no implication that one provider corroborates another.
 if(inputs.length<1||inputs.length>6)throw Error("Combine one to six snapshots at once");
 const sources=inputs.map(normalizeSnapshot);
 const stamps=sources.map(x=>Date.parse(x.captured_at));
 const earliest=Math.min(...stamps),latest=Math.max(...stamps);
 if(latest-earliest>24*60*60*1000)
  throw Error("Source snapshots were captured more than 24 hours apart; recapture before combining");
 const all=sources.flatMap(x=>x.facts);
 if(all.length>MAX_FACTS)throw Error("Combined snapshot exceeds evidence fact limit");
 const inventory=sources.flatMap(x=>x.permission_inventory||[]);
 return normalizeSnapshot({schema:SCHEMA,captured_at:new Date(latest).toISOString(),facts:all,
  permission_inventory:inventory.length?inventory:undefined});
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
 const snapshot=normalizeSnapshot(input), groups=factsMap(snapshot),findings=[],controls=[];
 for(const [id,observations] of groups){
  const [provider,...rest]=id.split("|"), asset={provider,asset:rest.join("|")};
  const yes=x=>observations.get(x)?.value===true;
  const no=x=>observations.get(x)?.value===false;
  const f=x=>observations.get(x);
  if(provider==="github"){
   if(yes("workflow_unpinned_actions")){
    emit(findings,asset,"workflow_action_integrity",[f("workflow_unpinned_actions")],
      ["workflow_unpinned_actions"]);
   }
   if(yes("runtime_ssh_keyscan")&&!yes("ssh_host_key_pinned")){
    emit(findings,asset,"ssh_host_trust",[f("runtime_ssh_keyscan"),...(f("ssh_host_key_pinned")?[f("ssh_host_key_pinned")]:[])],
      ["runtime_ssh_keyscan","ssh_host_key_pinned"]);
   }
   if(yes("workflow_explicit_read_only_permissions")){
    const item=f("workflow_explicit_read_only_permissions");
    controls.push({id:asset.provider+"|"+asset.asset+"|read_only_permissions",provider,
     asset:asset.asset,key:"read_only_permissions",
     title:"Explicit read-only token permissions declared",
     interpretation:"All recognized permissions declarations in this workflow restrict token scopes to read or none. This is positive configuration evidence, not independent proof of effective token permissions or repository policy.",
     evidence:[{signal:item.signal,observed_value:item.value,observed_at:item.observed_at,source_url:item.source_url}]});
   }
   if(yes("workflow_token_write_permission")&&yes("workflow_pull_request_target_trigger")){
    emit(findings,asset,"privileged_pr_trigger",
     [f("workflow_token_write_permission"),f("workflow_pull_request_target_trigger")],
     ["workflow_token_write_permission","workflow_pull_request_target_trigger"]);
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
  if(provider==="vercel"){
   if(yes("vercel_recent_preview_observed")&&no("vercel_deployment_protection_configured")){
    emit(findings,asset,"vercel_preview_visibility",
      [f("vercel_recent_preview_observed"),f("vercel_deployment_protection_configured")],
      ["vercel_recent_preview_observed","vercel_deployment_protection_configured"]);
   }
   if(yes("vercel_latest_production_errored")){
    emit(findings,asset,"vercel_production_release",[f("vercel_latest_production_errored")],
      ["vercel_latest_production_errored"]);
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
   facts:snapshot.facts.length,findings,controls,
   counts:{high:findings.filter(x=>x.level==="high").length,
           review:findings.filter(x=>x.level==="review").length,
           unknown:findings.filter(x=>x.level==="unknown").length},
   conclusion:"Configuration review candidates. Not confirmed compromises, exploitable vulnerabilities, or causal effectiveness."};
}
// Pure presentation-only grouping. Raw per-workflow findings remain in the
// signed-by-hash receipt; no finding is silently merged away.
// Workflow triage is a presentation of overlapping source observations, never
// an exploitability score or a change to a signed evidence receipt.
export function workflowTriage(input){
 const snapshot=normalizeSnapshot(input);
 if(!snapshot.coverage)return [];
 const assets=new Map();
 for(const fact of snapshot.facts){
  if(fact.provider!=="github"||
     !fact.asset.startsWith(snapshot.coverage.repository+":.github/workflows/"))
   continue;
  if(!["workflow_unpinned_actions","runtime_ssh_keyscan",
       "workflow_token_write_permission"].includes(fact.signal))continue;
  let entry=assets.get(fact.asset);
  if(!entry){
   entry={asset:fact.asset,name:fact.asset.slice(snapshot.coverage.repository.length+1+
      ".github/workflows/".length),flags:{},source_url:fact.source_url};
   assets.set(fact.asset,entry);
  }
  entry.flags[fact.signal]=fact.value;
  if(fact.signal==="workflow_unpinned_actions")entry.source_url=fact.source_url;
 }
 const order=["write","mutable","ssh"];
 const labels={write:"write-level permissions",mutable:"mutable action refs",ssh:"SSH host discovery"};
 const output=[];
 for(const value of assets.values()){
  const state={
   write:value.flags.workflow_token_write_permission,
   mutable:value.flags.workflow_unpinned_actions,
   ssh:value.flags.runtime_ssh_keyscan
  };
  const positive=order.filter(k=>state[k]===true);
  const unverified=order.filter(k=>state[k]===undefined||state[k]==="unknown");
  // Never label a workflow as having none of these conditions unless all
  // three signals were actually observed and explicitly false.
  const type=positive.length?positive.join("+"):
    unverified.length?"incomplete":"none";
  const name=positive.length?positive.map(k=>labels[k]).join(" + "):
    unverified.length?"Insufficient evidence":"No matched triage conditions";
  const item={asset:value.asset,workflow:value.name,source_url:value.source_url,
   category:type,label:name,indicator_count:positive.length,
   unknown_count:unverified.length};
  let group=output.find(x=>x.category===type);
  if(!group){
   group={category:type,label:name,indicator_count:positive.length,
    workflows:[]};
   output.push(group);
  }
  group.workflows.push(item);
 }
 for(const group of output)group.workflows.sort((a,b)=>a.workflow.localeCompare(b.workflow));
 output.sort((a,b)=>b.indicator_count-a.indicator_count||
   (a.category==="incomplete"?-1:b.category==="incomplete"?1:0)||
   a.category.localeCompare(b.category));
 return output;
}
export function groupReviewFindings(findings){
 if(!Array.isArray(findings))throw Error("Invalid report findings");
 const groups=new Map();
 for(const item of findings){
  const key=item.provider+"|"+item.check+"|"+item.level;
  let group=groups.get(key);
  if(!group){
   group={...item,evidence:[],affected:0};
   groups.set(key,group);
  }
  group.affected++;
  for(const fact of item.evidence)group.evidence.push({...fact,asset:item.asset});
 }
 return [...groups.values()].map(group=>{
  if(group.affected>1)return {...group,
   title:group.affected+" workflows: "+group.title,
   asset:group.affected+" workflow files"};
  return group;
 });
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
// Keep deterministic compatibility for receipts exported before the 2026-11-16
// policy expansion. Earlier v1 assessment documents had no "controls" field.
async function historicalV1Proof(snapshot,followup=null){
 const baseline=normalizeSnapshot(snapshot),after=followup?normalizeSnapshot(followup):null;
 const current=analyzeSnapshot(baseline);
 const {controls, ...assessment}=current;
 const comparison=after?compareSnapshots(baseline,after):null;
 const payload={schema:"qira-proof/evidence-v1",baseline,after,assessment,comparison,
  attestation:"self-contained deterministic calculation, NOT source authentication, a signature, or proof of prevention"};
 return {...payload,sha256:await sha256(canonical(payload))};
}
// v2 is retained for checksums already issued with the first permission rule set.
async function historicalV2Proof(snapshot,followup=null){
 const baseline=normalizeSnapshot(snapshot),after=followup?normalizeSnapshot(followup):null;
 if(baseline.permission_inventory||after?.permission_inventory)
  throw Error("v2 receipts cannot contain new permission inventories");
 const assessment=analyzeSnapshot(baseline),comparison=after?compareSnapshots(baseline,after):null;
 const payload={schema:"qira-proof/evidence-v2",policy_version:"2026-11-16-static-workflow-v2",
  baseline,after,assessment,comparison,
  attestation:"self-contained deterministic calculation, NOT source authentication, a signature, or proof of prevention"};
 return {...payload,sha256:await sha256(canonical(payload))};
}
export async function proof(snapshot,followup=null){
 const baseline=normalizeSnapshot(snapshot),after=followup?normalizeSnapshot(followup):null;
 const assessment=analyzeSnapshot(baseline),comparison=after?compareSnapshots(baseline,after):null;
 const payload={schema:"qira-proof/evidence-v3",policy_version:"2026-11-16-source-scopes-v3",
  baseline,after,assessment,comparison,
  attestation:"self-contained deterministic calculation, NOT source authentication, a signature, or proof of prevention"};
 return {...payload,sha256:await sha256(canonical(payload))};
}
export async function verifyProof(doc){
 if(!plain(doc)||typeof doc.sha256!=="string"||!/^[a-fA-F0-9]{64}$/.test(doc.sha256))
  return false;
 try{
  const fresh=doc.schema==="qira-proof/evidence-v3"?await proof(doc.baseline,doc.after):
   doc.schema==="qira-proof/evidence-v2"?await historicalV2Proof(doc.baseline,doc.after):
   doc.schema==="qira-proof/evidence-v1"?await historicalV1Proof(doc.baseline,doc.after):null;
  return !!fresh&&canonical(fresh)===canonical(doc);
 }catch{return false}
}
