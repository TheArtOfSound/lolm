import {SCHEMA,normalizeSnapshot,mergeSnapshots,analyzeSnapshot,compareSnapshots,proof,verifyProof,groupReviewFindings}
from "./core.mjs";
import {renderHumanReport} from "./report.mjs";

const DEMO_DATE="2026-11-15T19:00:00Z";
const DEMO={
 schema:SCHEMA,captured_at:DEMO_DATE,
 facts:[
  {provider:"github",asset:"fictional-org/operations-demo",signal:"runtime_ssh_keyscan",value:true,
   source_url:"https://example.org/fictional-workflow",observed_at:DEMO_DATE},
  {provider:"github",asset:"fictional-org/operations-demo",signal:"ssh_host_key_pinned",value:"unknown",
   source_url:"https://example.org/fictional-workflow",observed_at:DEMO_DATE},
  {provider:"github",asset:"fictional-org/operations-demo",signal:"repo_branch_protection_verifiable",value:"unknown",
   source_url:"https://example.org/fictional-rules",observed_at:DEMO_DATE},
  {provider:"cloudflare",asset:"fictional-worker",signal:"worker_preview_enabled",value:true,
   source_url:"https://example.org/fictional-worker",observed_at:DEMO_DATE},
  {provider:"cloudflare",asset:"fictional-worker",signal:"worker_public_enabled",value:true,
   source_url:"https://example.org/fictional-worker",observed_at:DEMO_DATE},
  {provider:"cloudflare",asset:"fictional-worker",signal:"worker_privileged_bindings",value:true,
   source_url:"https://example.org/fictional-worker",observed_at:DEMO_DATE},
 ]
};
function sampleAfter(){
 const date="2026-11-16T19:00:00Z";
 return {schema:SCHEMA,captured_at:date,facts:DEMO.facts.map(f=>{
  const changed=f.signal==="worker_preview_enabled"?false:
   f.signal==="ssh_host_key_pinned"||f.signal==="repo_branch_protection_verifiable"?true:f.value;
  return {...f,value:changed,observed_at:date};
 })};
}
const state={before:normalizeSnapshot(DEMO),after:null,mode:"idle",tab:"assessment",last:null,coverage:null};
const el=id=>document.getElementById(id);
const clear=e=>e.replaceChildren();
function node(tag,cls,value){const d=document.createElement(tag);if(cls)d.className=cls;if(value!==undefined)d.textContent=value;return d}
function status(message,isError=false){el("status").textContent=message;el("status").style.color=isError?"#f2b1aa":""}
function buttonTab(tab){
 state.tab=tab;
 document.querySelectorAll("[data-tab]").forEach(b=>{
  const on=b.dataset.tab===tab;b.classList.toggle("active",on);
  b.setAttribute("aria-selected",String(on));b.tabIndex=on?0:-1;
 });
 document.querySelectorAll(".tabcontent").forEach(p=>p.hidden=p.id!==tab);
 el("workTitle").textContent={assessment:"Assessment",recheck:"Configuration recheck",evidence:"Evidence export & verification"}[tab];
}
// WAI-ARIA tab pattern: arrow keys move and activate the next tab; Home/End
// move to the first/last. Native Tab reaches the selected tab then panel.
const tabOrder=["assessment","recheck","evidence"];
document.querySelectorAll("[data-tab]").forEach(control=>{
 control.addEventListener("keydown",event=>{
  if(!["ArrowRight","ArrowLeft","Home","End"].includes(event.key))return;
  event.preventDefault();
  const current=tabOrder.indexOf(control.dataset.tab);
  const next=event.key==="Home"?0:event.key==="End"?tabOrder.length-1:
   (current+(event.key==="ArrowRight"?1:-1)+tabOrder.length)%tabOrder.length;
  buttonTab(tabOrder[next]);
  const nextControl=[...document.querySelectorAll("[data-tab]")].find(x=>x.dataset.tab===tabOrder[next]);
  nextControl?.focus?.();
 });
});
function render(){
 const report=analyzeSnapshot(state.before);
 const showing=state.mode!=="idle";
 el("reportIntro").hidden=showing;
 el("assessmentData").hidden=!showing;
 el("exportButton").disabled=!showing;
 el("humanReportButton").disabled=!showing;
 el("sampleBanner").hidden=state.mode!=="demo";
 document.body.dataset.reportType=state.mode==="idle"?"unstarted":state.mode==="demo"?"example":"customer";
 el("assetsCount").textContent=report.assets;
 el("reviewCount").textContent=new Set(report.findings.filter(x=>x.level!=="unknown").map(x=>x.check)).size;
 el("observationsCount").textContent=report.counts.review+report.counts.high;
 el("unknownCount").textContent=report.counts.unknown;
 el("factsCount").textContent=report.facts;
 const coverageBox=el("scanCoverage");
 coverageBox.hidden=!state.coverage||state.mode!=="connected";
 if(!coverageBox.hidden){
  const c=state.coverage;
  coverageBox.textContent="Repository workflow review: "+c.assessed+" of "+c.discovered+
   " discovered workflows assessed at commit "+c.commit.slice(0,12)+
   ". "+(c.complete?"All discovered workflow files were inspected.":
     "Partial coverage: "+c.skipped+" failed or skipped, "+
     (c.truncated?"more workflows than this scan can cover.":"review the unscanned files separately."))+
   " This is a bounded configuration check, not a full repository security audit.";
 }
 el("baselineState").textContent=state.mode==="demo"?"Sample":"Loaded";
 el("baselineName").textContent=state.mode==="demo"?"Fictional demo · "+report.facts+" facts":
  (state.mode==="composed"?"Combined provider snapshot":state.mode==="connected"?"Connected GitHub workflow":"Private local snapshot")+" · "+report.facts+" facts · "+state.before.captured_at;
 el("followupState").textContent=state.after?"Loaded":"Empty";
 el("followupName").textContent=state.after?"Follow-up · "+state.after.captured_at:"No later snapshot selected";
 const findings=el("findings");clear(findings);
 if(!report.findings.length){findings.appendChild(node("div","empty","No configured rule matched these facts. This is not a clean bill of health."));}
 const visibleFindings=state.mode==="connected"&&state.before.coverage?
  groupReviewFindings(report.findings):report.findings;
 visibleFindings.forEach((x,index)=>{
  const card=node("details","finding");
  card.open=index===0;
  const head=node("summary","finding-head"),label=node("div"),title=node("div","finding-title",x.title);
  label.appendChild(title);label.appendChild(node("div","finding-meta",
   x.provider.toUpperCase()+" / "+x.asset+" · "+x.category+" · "+x.confidence));
  head.appendChild(label);head.appendChild(node("span","severity "+x.level,x.level==="unknown"?"Unverified":x.level==="review"?"Review":"Elevated"));
  card.appendChild(head);
  const body=node("div","finding-body");
  body.appendChild(node("p","",x.interpretation));
  body.appendChild(node("div","section-label","Recommended verification"));
  body.appendChild(node("p","",x.next));
  body.appendChild(node("div","section-label","Observed evidence"));
  const evidence=node("div","evidence");
  x.evidence.forEach(f=>{
   if(state.mode==="demo"){evidence.appendChild(node("span","chip","Fictional · "+f.signal+" = "+String(f.observed_value)));return;}
   const workflowName=typeof f.asset==="string"&&f.asset.includes(":.github/workflows/")?
    f.asset.split(":.github/workflows/")[1]+" · ":"";
   const a=node("a","",workflowName+f.signal+" = "+String(f.observed_value));
   a.href=f.source_url;a.target="_blank";a.rel="noopener noreferrer";
   a.title="Open declared provider evidence: "+f.source_url;
   evidence.appendChild(a);
  });
  body.appendChild(evidence);card.appendChild(body);findings.appendChild(card);
 });
 const positiveSection=el("positiveControlsSection");
 const positiveBox=el("positiveControls");clear(positiveBox);
 positiveSection.hidden=!showing||!report.controls?.length;
 if(!positiveSection.hidden){
  const controls=state.before.coverage?
   groupReviewFindings(report.controls.map(x=>({...x,check:x.key,level:"good"}))):
   report.controls.map(x=>({...x,check:x.key,level:"good"}));
  controls.forEach((x,index)=>{
   const card=node("details","finding");card.open=index===0;
   const header=node("summary","finding-head"),label=node("div");
   label.appendChild(node("div","finding-title",x.title));
   label.appendChild(node("div","finding-meta",x.provider.toUpperCase()+" / "+x.asset+" · declared safeguard"));
   header.appendChild(label);
   header.appendChild(node("span","severity good","Observed"));
   card.appendChild(header);
   const body=node("div","finding-body");
   body.appendChild(node("p","",x.interpretation));
   const evidence=node("div","evidence");
   x.evidence.forEach(f=>{
    const file=typeof f.asset==="string"&&f.asset.includes(":.github/workflows/")?
      f.asset.split(":.github/workflows/")[1]+" · ":"";
    const a=node("a","",file+"declaration");
    a.href=f.source_url;a.target="_blank";a.rel="noopener noreferrer";
    a.title="Open exact declared evidence source";
    evidence.appendChild(a);
   });
   body.appendChild(evidence);card.appendChild(body);positiveBox.appendChild(card);
  });
 }
 const writeSection=el("writeAccessSection");
 const writeBox=el("writeAccessInventory");clear(writeBox);
 const declaredWrite=state.before.facts.filter(f=>f.provider==="github"&&
  f.signal==="workflow_token_write_permission"&&f.value===true);
 const unresolvedPermission=state.before.facts.filter(f=>f.provider==="github"&&
  f.signal==="workflow_token_write_permission"&&f.value==="unknown");
 writeSection.hidden=!showing||(!declaredWrite.length&&!unresolvedPermission.length);
 if(!writeSection.hidden){
  const details=node("details","finding");details.open=true;
  const heading=node("summary","finding-head"),label=node("div");
  label.appendChild(node("div","finding-title",declaredWrite.length+
   " workflows declare write-level permissions"+
   (unresolvedPermission.length?" · "+unresolvedPermission.length+" cannot be classified":"")));
  heading.appendChild(label);
  heading.appendChild(node("span","severity unknown","Authorization inventory"));
  details.appendChild(heading);
  const body=node("div","finding-body");
  body.appendChild(node("p","",
   "Inspect the actual scopes and trigger context at each source. A write declaration may be intentional, including OIDC publishing; these are not automatically vulnerabilities. Unknown declarations need manual validation."));
  const links=node("div","evidence");
  const inventory=new Map((state.before.permission_inventory||[]).map(x=>[x.asset,x.scopes]));
  for(const f of [...declaredWrite,...unresolvedPermission]){
   const name=f.asset.includes(":.github/workflows/")?
    f.asset.split(":.github/workflows/")[1]:f.asset;
   const precise=inventory.get(f.asset)||[];
   if(precise.length){
    for(const item of precise){
     const a=node("a","",name+" · "+item.scope+": write");
     a.href=item.source_url;a.target="_blank";a.rel="noopener noreferrer";
     a.title="Open exact declared write scope in GitHub Actions workflow";
     links.appendChild(a);
    }
   }else{
    const a=node("a","",name+" · "+(f.value===true?"write scopes not enumerated":"unverified"));
    a.href=f.source_url;a.target="_blank";a.rel="noopener noreferrer";
    a.title="Open declared workflow permissions at source";
    links.appendChild(a);
   }
  }
  body.appendChild(links);details.appendChild(body);writeBox.appendChild(details);
 }
 const deltaBox=el("deltas");clear(deltaBox);
 if(!state.after){
  const empty=node("div","empty");
  empty.appendChild(node("strong","","No follow-up snapshot yet"));
  empty.appendChild(node("div","","Import a second local JSON file or choose Sample recheck. No active infrastructure modification happens here."));
  deltaBox.appendChild(empty);
 }else{
  const comparison=compareSnapshots(state.before,state.after);
  comparison.deltas.forEach(x=>{
   const d=node("div","delta");d.appendChild(node("b","",x.title));
   d.appendChild(node("span","label",x.state.replaceAll("-"," ").toUpperCase()));
   d.appendChild(node("span","",": "+x.explanation));deltaBox.appendChild(d);
  });
  if(!comparison.deltas.length)deltaBox.appendChild(node("div","empty","No previous review conditions to compare."));
  deltaBox.appendChild(node("div","note",comparison.conclusion));
 }
 status(state.mode==="idle"?"No assessment yet. Connect GitHub or explore the example to begin.":
 state.mode==="demo"?"DEMONSTRATION: fictional source data. Import authorized evidence to run a real configuration review.":
 state.mode==="connected"?"GITHUB APP: selected read-only metadata was retrieved transiently through this Worker's server. Analysis occurs in your browser; source origin is not independently attested.":
 state.mode==="composed"?"MULTI-SOURCE: separate read-only evidence was combined locally. The source links are declarations, not authenticated attestations.":
 "PRIVATE LOCAL ANALYSIS: imported files remain in this browser. Source identity and authorization are not cryptographically attested.");
}
async function readSnapshot(file){
 if(!file||file.size>512_000)throw Error("Choose a JSON snapshot smaller than 500 KB");
 const input=JSON.parse(await file.text());
 return normalizeSnapshot(input);
}
const LOCAL_COLLECTOR="python product/qira-proof/collector.py";
const PROVIDER_GUIDES={
 github:["# Set GITHUB_TOKEN locally to a read-only token for your chosen repository.",
  LOCAL_COLLECTOR+' --github-workflow "OWNER/REPO:.github/workflows/deploy.yml" --out qira-baseline.json'],
 cloudflare:["# Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID locally; allow Workers Scripts read only.",
  LOCAL_COLLECTOR+" --cloudflare-worker YOUR_WORKER --out qira-baseline.json"],
 vercel:["# Set VERCEL_TOKEN locally; for team resources, also set VERCEL_TEAM_ID.",
  LOCAL_COLLECTOR+" --vercel-project YOUR_PROJECT --out qira-baseline.json"],
 combined:["# Set relevant provider tokens locally; this browser never receives them.",
  LOCAL_COLLECTOR+' --github-workflow "OWNER/REPO:.github/workflows/deploy.yml" --cloudflare-worker YOUR_WORKER --vercel-project YOUR_PROJECT --out qira-baseline.json']
};
function renderProviderGuide(){
 const choice=el("providerGuide").value;
 const lines=PROVIDER_GUIDES[choice]||PROVIDER_GUIDES.github;
 el("providerCommand").textContent=lines.join("\n");
 el("providerCommandStatus").textContent="Replace example resource names with resources you control. Run locally, then import the JSON.";
}
el("providerGuide").addEventListener("change",renderProviderGuide);
el("copyProviderCommand").addEventListener("click",async()=>{
 try{
  if(!navigator.clipboard?.writeText)throw Error("clipboard unsupported");
  await navigator.clipboard.writeText(el("providerCommand").textContent);
  el("providerCommandStatus").textContent="Copied. Confirm the resource scope and token permissions before running locally.";
 }catch{
  el("providerCommandStatus").textContent="Clipboard unavailable; select and copy the displayed command instead.";
 }
});
renderProviderGuide();
el("augmentInput").addEventListener("change",async e=>{
 const file=e.target.files?.[0];
 if(!file)return;
 try{
  if(state.mode==="idle"||state.mode==="demo")
   throw Error("Start with real authorized evidence; fictional examples cannot be combined");
  const additional=await readSnapshot(file);
  state.before=mergeSnapshots(state.before,additional);
  state.after=null;
  state.mode="composed";
  render();
  buttonTab("assessment");
 }catch(error){status("Additional evidence was rejected: "+error.message,true)}
 e.target.value="";
});
el("baselineInput").addEventListener("change",async e=>{
 const file=e.target.files?.[0];
 if(!file)return;
 try{state.before=await readSnapshot(file);state.after=null;state.mode="private";render();buttonTab("assessment");}
 catch(error){status("Baseline was rejected: "+error.message,true)}
 e.target.value="";
});
el("followupInput").addEventListener("change",async e=>{
 const file=e.target.files?.[0];if(!file)return;
 try{
  if(state.mode==="demo"||state.mode==="idle")throw Error("Load a real baseline before comparing a real follow-up");
  state.after=await readSnapshot(file);render();buttonTab("recheck");
 }catch(error){status("Follow-up rejected: "+error.message,true)}
 e.target.value="";
});
el("demoButton").addEventListener("click",()=>{state.before=normalizeSnapshot(DEMO);state.after=null;state.mode="demo";render();buttonTab("assessment")});
el("startSample").addEventListener("click",()=>{
 state.before=normalizeSnapshot(DEMO);state.after=null;state.mode="demo";render();buttonTab("assessment");
});
el("jumpDemo").addEventListener("click",()=>{
 state.before=normalizeSnapshot(DEMO);state.after=null;state.mode="demo";
 render();buttonTab("assessment");
 document.getElementById("workspace")?.scrollIntoView?.({behavior:"smooth",block:"start"});
});
el("demoRecheck").addEventListener("click",()=>{
 if(state.mode!=="demo"){status("Reset to the fictional demo to load its sample follow-up",true);return}
 state.after=normalizeSnapshot(sampleAfter());render();buttonTab("recheck");
});
el("clearFollowup").addEventListener("click",()=>{state.after=null;render();buttonTab("assessment")});
document.querySelectorAll("[data-tab]").forEach(b=>b.addEventListener("click",()=>buttonTab(b.dataset.tab)));
function downloadFile(content,filename,type){
 const blob=new Blob([content],{type});
 const url=URL.createObjectURL(blob),a=document.createElement("a");
 a.href=url;a.download=filename;a.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function downloadJson(data,filename){
 downloadFile(JSON.stringify(data,null,2),filename,"application/json");
}
el("exportButton").addEventListener("click",async()=>{
 try{
  const artifact=await proof(state.before,state.after);
  state.last=artifact;
  el("digestValue").textContent=artifact.sha256;
  el("verificationState").textContent="Locally generated. Hash is not a digital signature or provider authentication.";
  downloadJson(artifact,"qira-proof-evidence.json");
 }catch(error){el("verificationState").textContent="Unable to generate evidence: "+error.message;}
});
el("humanReportButton").addEventListener("click",async()=>{
 try{
  if(state.mode==="idle")throw Error("Start an assessment before exporting a customer report.");
  const artifact=await proof(state.before,state.after);
  const html=await renderHumanReport(artifact,{sample:state.mode==="demo"});
  state.last=artifact;
  el("digestValue").textContent=artifact.sha256;
  el("verificationState").textContent=state.mode==="demo"?
   "Downloaded a clearly labeled fictional example. It is not a customer review.":
   "Printable assessment downloaded. Open the HTML file locally and use Print → Save as PDF. Export the companion JSON evidence receipt separately for reproducible verification.";
  downloadFile(html,"qira-proof-configuration-review.html","text/html;charset=utf-8");
 }catch(error){el("verificationState").textContent="Unable to export human report: "+error.message;}
});
el("verifyButton").addEventListener("click",()=>el("verifyInput").click());
el("verifyInput").addEventListener("change",async event=>{
 const f=event.target.files?.[0];if(!f)return;
 try{
  if(f.size>1_000_000)throw Error("Evidence exceeds 1 MB");
  const artifact=JSON.parse(await f.text());
  const okay=await verifyProof(artifact);
  el("verificationState").textContent=okay?
   "PASS: document, source facts, findings, and digest match a fresh local deterministic calculation. Provider origin is not verified.":
   "FAIL: evidence does not match the deterministic proof calculation, or its fields were altered.";
  el("digestValue").textContent=okay?artifact.sha256:"Verification failed";
  buttonTab("evidence");
 }catch(error){el("verificationState").textContent="Evidence rejected: "+error.message}
 event.target.value="";
});

const git={connected:false,csrf:null,repos:[],selectionVersion:0};
function gitMessage(value,isError=false){
 const out=el("gitMessage");out.textContent=value;out.style.color=isError?"#f2b1aa":"";
}
async function githubApi(path,options={}){
 const response=await fetch(path,{credentials:"same-origin",cache:"no-store",...options});
 if(!response.ok)throw Error(response.status===401?"GitHub connection expired. Connect again.":
  response.status===403?"Your GitHub App authorization does not permit this resource.":
  "GitHub read-only metadata could not be retrieved (HTTP "+response.status+").");
 return response.json();
}
async function githubInspect(path,selection){
 if(!git.csrf)throw Error("GitHub session is unavailable. Reconnect.");
 return githubApi(path,{method:"POST",
   headers:{"content-type":"application/json","x-qira-csrf":git.csrf},
   body:JSON.stringify(selection)});
}
function selectOptions(id,items,label,value,placeholder){
 const control=el(id);
 control.replaceChildren();
 control.appendChild(new Option(placeholder,""));
 for(const item of items)control.appendChild(new Option(label(item),value(item)));
 control.disabled=items.length===0;
 control.value="";
}
function resetWorkflowSelection(){
 selectOptions("gitWorkflow",[],x=>x.path,x=>x.path,"Choose workflow");
 el("gitAssess").disabled=true;
 el("gitScanAll").disabled=true;
}
function renderRepositoryMatches(){
 const query=el("gitRepoSearch").value.trim().toLowerCase();
 const matches=git.repos.filter(x=>x.name.toLowerCase().includes(query));
 selectOptions("gitRepository",matches,x=>x.name,x=>x.name,
  matches.length?"Choose repository":"No repositories match");
 el("gitRepoCount").textContent=matches.length+" of "+git.repos.length+" available repositories shown"+
  (query?" for this filter.":".");
 resetWorkflowSelection();
}
el("gitRepoSearch").addEventListener("input",()=>{
 git.selectionVersion++;
 renderRepositoryMatches();
});
async function loadGithubInstallations(){
 const payload=await githubApi("/api/github/installations");
 selectOptions("gitInstallation",payload.items,x=>x.account+" · "+x.selection,x=>String(x.id),"Choose installation");
 git.repos=[];git.selectionVersion++;
 el("gitRepoSearch").value="";el("gitRepoSearch").disabled=true;
 el("gitRepoCount").textContent="Choose an account to see its repositories.";
 selectOptions("gitRepository",[],x=>x.name,x=>x.name,"Choose repository");
 resetWorkflowSelection();
 gitMessage(payload.items.length?"Your account is connected. Choose the GitHub account you want to review.":
 "No authorized installations found. Install the read-only GitHub App, then reconnect.");
 if(payload.truncated)gitMessage("More than 50 installations found; this pilot lists the first 50.");
}
async function githubConnectionStatus(){
 try{
  const current=await githubApi("/api/github/status");
  git.connected=current.connected;
  git.csrf=current.csrf;
  el("gitConnect").hidden=!current.configured||current.connected;
  el("gitDisconnect").hidden=!current.connected;
  el("gitInstall").hidden=!current.install_url||current.connected;
  if(current.install_url)el("gitInstall").href=current.install_url;
  el("gitPicker").hidden=!current.connected;
  el("startCard").hidden=current.connected;
  el("gitBadge").textContent=!current.configured?"Pending setup":current.connected?"Connected":"Ready";
  document.body.dataset.githubConnection=!current.configured?"pending-setup":current.connected?"connected":"ready";
  el("gitStatus").textContent=!current.configured?
   "GitHub App registration and secure credentials are not configured yet. Manual JSON analysis remains available.":
   current.connected?"Authorized GitHub connection. Temporary session; selected metadata is processed without server storage.":
   "GitHub is ready. Choose Connect GitHub to approve read-only access.";
  if(current.connected)await loadGithubInstallations();
 }catch(error){
  el("gitBadge").textContent="Unavailable";
  document.body.dataset.githubConnection="error";
  el("gitStatus").textContent="Could not check GitHub connection availability.";
  gitMessage(error.message,true);
 }
}
el("gitInstallation").addEventListener("change",async event=>{
 const id=event.target.value,version=++git.selectionVersion;
 git.repos=[];el("gitRepoSearch").value="";el("gitRepoSearch").disabled=true;
 el("gitRepoCount").textContent="Loading authorized repositories…";
 selectOptions("gitRepository",[],x=>x.name,x=>x.name,"Choose repository");
 resetWorkflowSelection();
 if(!id)return;
 gitMessage("Loading authorized repositories…");
 try{
  const result=await githubInspect("/api/github/repos",{installation_id:Number(id)});
  if(version!==git.selectionVersion||el("gitInstallation").value!==id)return;
  git.repos=result.repos;
  el("gitRepoSearch").disabled=result.repos.length===0;
  renderRepositoryMatches();
  gitMessage(result.truncated?"Showing the first 100 authorized repositories. Search only filters this loaded set.":
   "Filter or select a repository to see its available workflows.");
 }catch(error){
  if(version!==git.selectionVersion)return;
  gitMessage(error.message,true);el("gitRepoCount").textContent="Unable to load repositories.";
 }
});
el("gitRepository").addEventListener("change",async event=>{
 const id=el("gitInstallation").value,repo=event.target.value;
 const version=++git.selectionVersion;
 resetWorkflowSelection();
 if(!id||!repo)return;
 gitMessage("Loading authorized workflow names…");
 try{
  const result=await githubInspect("/api/github/workflows",{installation_id:Number(id),repo});
  if(version!==git.selectionVersion||el("gitRepository").value!==repo)return;
  selectOptions("gitWorkflow",result.workflows,x=>x.path,x=>x.path,
   result.workflows.length?"Choose workflow":"No accessible workflows on this branch");
  el("gitScanAll").disabled=result.workflows.length===0;
  el("gitScanAll").textContent=result.workflows.length?
   "Review "+Math.min(result.workflows.length,20)+" repository workflows →":"Review repository workflows →";
  gitMessage(result.workflows.length?"Review the repository or select one workflow for a focused scan.":
   result.availability==="directory_not_found_or_inaccessible"?
   "This repository's workflow directory is absent or inaccessible. Choose a different repository, or inspect its GitHub App permissions.":
   "No supported GitHub Actions YAML workflows were found. Choose another repository.");
 }catch(error){
  if(version!==git.selectionVersion)return;
  gitMessage(error.message,true);
 }
});
el("gitWorkflow").addEventListener("change",event=>{
 el("gitAssess").disabled=!event.target.value;
});
async function runConnectedReview(workflow){
 const id=el("gitInstallation").value,repo=el("gitRepository").value;
 if(!id||!repo||!workflow)return;
 const all=workflow==="__all__";
 const button=el(all?"gitScanAll":"gitAssess");
 button.disabled=true;
 gitMessage(all?"Reviewing up to 20 authorized workflows at a fixed commit…":
  "Retrieving authorized configuration evidence…");
 try{
  const data=await githubInspect("/api/github/assessment",{installation_id:Number(id),repo,workflow});
  state.before=normalizeSnapshot(data.snapshot);
  state.after=null;state.mode="connected";state.coverage=data.coverage||null;
  render();buttonTab("assessment");
  if(data.coverage){
   const c=data.coverage;
   gitMessage(c.complete?"Reviewed all "+c.assessed+" discovered workflows. Related observations are grouped, with source links for each workflow.":
    "Review partially completed: "+c.assessed+" workflow(s) assessed; "+c.skipped+" skipped or failed"+
    (c.truncated?"; more than 20 available.":"")+". See coverage details in results.",!c.complete);
  }else gitMessage("Assessment ready. Your GitHub credentials stayed on the server.");
  document.getElementById("workspace")?.scrollIntoView?.({behavior:"smooth",block:"start"});
 }catch(error){gitMessage(error.message,true)}
 finally{button.disabled=false}
}
el("gitAssess").addEventListener("click",async()=>{
 await runConnectedReview(el("gitWorkflow").value);
});
el("gitScanAll").addEventListener("click",async()=>{
 await runConnectedReview("__all__");
});
el("gitDisconnect").addEventListener("click",async()=>{
 if(!git.csrf)return;
 try{
  await githubApi("/api/github/disconnect",{method:"POST",headers:{"content-type":"application/json","x-qira-csrf":git.csrf},body:"{}"});
  state.before=normalizeSnapshot(DEMO);state.after=null;state.mode="idle";state.coverage=null;
  render();buttonTab("assessment");gitMessage("Local session cleared. GitHub authorization must be revoked separately in GitHub if desired.");
  await githubConnectionStatus();
 }catch(error){gitMessage(error.message,true)}
});
const githubParams=new URL(location.href).searchParams;
const githubResult=githubParams.get("github");
if(githubResult==="failed"){
 const reasons={
  authorization_denied:"GitHub authorization was declined. Approve the request to connect.",
  state_missing:"The secure sign-in cookie was missing. Start again in the same browser tab; ensure cookies are enabled.",
  state_expired:"The sign-in window expired after ten minutes. Start a new connection.",
  state_mismatch:"The sign-in session did not match. Start again from Qira and finish in the same browser.",
  code_missing:"GitHub did not return a usable authorization code. Start a fresh connection.",
  client_credentials:"Qira's GitHub App credentials were rejected. The site owner must check the App Client ID and secret.",
  callback_mismatch:"GitHub rejected Qira's callback URL. The site owner must correct the exact callback address in GitHub App settings.",
  token_expiration_disabled:"This GitHub App returned a non-expiring token, which Qira refuses. The site owner must enable user-to-server token expiration.",
  token_invalid:"GitHub returned an unsupported token response. The site owner must check the App's authorization configuration.",
  authorization_code_rejected:"GitHub rejected the one-time authorization code. Start Connect GitHub again from Qira; do not reload or reuse a callback URL.",
  email_unverified:"GitHub requires a verified primary email address for this account. Verify it in GitHub, then reconnect.",
  app_suspended:"GitHub reports that the Qira App is suspended. The App owner must resolve this with GitHub.",
  exchange_transport:"Qira could not establish the token-exchange connection to GitHub. The site owner must inspect Cloudflare Worker connectivity.",
  exchange_http_4xx:"GitHub returned an HTTP client error without a recognized OAuth error code. The Qira owner must check the App registration and exchange configuration.",
  exchange_http_5xx:"GitHub returned a server error during authorization. Try a new connection later.",
  provider_rejected:"GitHub refused the token exchange with an unrecognized error code. The Qira owner must inspect the sanitized Worker diagnostics.",
  provider_unavailable:"An unexpected OAuth exchange error occurred. The Qira owner must inspect the sanitized Worker diagnostics.",
  session_unavailable:"Qira could not protect the returned session. The site owner needs to repair the secure session configuration."
 };
 gitMessage(reasons[githubParams.get("reason")]||
  "GitHub authorization failed. Start a new connection or contact Qira support.",true);
}
if(githubResult){const cleaned=new URL(location.href);cleaned.searchParams.delete("github");cleaned.searchParams.delete("reason");history.replaceState(null,"",cleaned.pathname+cleaned.search+cleaned.hash);}
render();buttonTab("assessment");document.body.dataset.qiraBoot="ready";githubConnectionStatus();
