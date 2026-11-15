import {CONTROL_INFO,SCENARIOS,evaluate} from "./engine.mjs";
import {robustAnalysis} from "./robustness.mjs";

function renderPage(nonce){
return String.raw`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>EVENT HORIZON / Qira Research</title><meta name="description" content="A synthetic, counterfactual security policy observatory. Model defender tradeoffs without targeting real systems."><style nonce="__NONCE__">
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f5f4f0;background:#101315;font-size:14px;line-height:1.45;font-synthesis:none}*{box-sizing:border-box}body{margin:0;min-height:100vh}button,select,input{font:inherit}button{cursor:pointer}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #a8d2bf;outline-offset:3px}.shell{max-width:1450px;margin:auto;padding:24px 32px 48px}.top{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #303737;padding-bottom:17px}.brand{font-weight:800;letter-spacing:.19em;font-size:12px}.brand span{color:#bcdbcd}.topright{display:flex;gap:12px;align-items:center;color:#9da9a5;font-size:11px;letter-spacing:.07em;text-transform:uppercase}.pulse{width:7px;height:7px;border-radius:50%;background:#a9d7bf;box-shadow:0 0 0 4px #a9d7bf18}.hero{padding:28px 0 24px;display:flex;gap:22px;justify-content:space-between;align-items:end}.kicker{font-size:11px;letter-spacing:.19em;text-transform:uppercase;color:#a8d3bc;font-weight:700}.hero h1{font-size:clamp(34px,5vw,60px);font-weight:550;letter-spacing:-.063em;line-height:1.03;margin:10px 0}.hero h1 em{font-family:Georgia,serif;font-style:italic;color:#b9d6ca;font-weight:400}.hero p{max-width:690px;color:#acb8b3;margin:8px 0 0;font-size:13px}.pill{border:1px solid #486657;border-radius:999px;padding:10px 14px;letter-spacing:.08em;text-transform:uppercase;color:#c8e8d4;white-space:nowrap;font-size:10px}.tabs{display:flex;gap:20px;border-bottom:1px solid #303737;margin-bottom:18px}.tab{background:none;border:0;border-bottom:2px solid transparent;color:#8f9a96;padding:12px 1px;text-transform:uppercase;letter-spacing:.14em;font-size:10px;font-weight:750}.tab.active{border-bottom-color:#b5d4c1;color:#f3f4ef}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:15px}.metric{border:1px solid #303939;background:#181d1e;padding:16px 17px;min-height:106px}.metric .label{color:#a1ada6;text-transform:uppercase;letter-spacing:.1em;font-size:10px}.metric .val{font-size:30px;font-weight:600;letter-spacing:-.04em;margin:9px 0 1px}.metric .hint{font-size:10px;color:#8b9892}.accent{color:#b4d7bd}.amber{color:#edca87}.rose{color:#e6a09d}.content-grid{display:grid;grid-template-columns:minmax(250px,330px) minmax(0,1fr);gap:13px}.panel{border:1px solid #333e3b;background:#181d1e;overflow:hidden}.panel-header{padding:17px 18px 13px;border-bottom:1px solid #313b38;display:flex;justify-content:space-between;align-items:center;gap:12px}.panel-title{text-transform:uppercase;letter-spacing:.15em;font-size:10px;font-weight:800;color:#c0d1c6}.muted{color:#9da9a4}.small{font-size:11px}.controls{padding:9px 14px}.control{display:flex;align-items:center;justify-content:space-between;padding:11px 5px;gap:10px;border-bottom:1px solid #293330;cursor:pointer}.control:last-child{border-bottom:0}.ctitle{font-weight:650;font-size:12px}.csub{font-size:10px;color:#95a49b;margin-top:3px}.switch{appearance:none;border:1px solid #62726a;width:38px;height:22px;flex:0 0 38px;border-radius:999px;background:#2b3332;position:relative;transition:.15s}.switch:before{content:"";width:14px;height:14px;border-radius:50%;background:#9ba8a1;position:absolute;left:3px;top:3px;transition:.15s}.switch:checked{background:#628c73;border-color:#88bb98}.switch:checked:before{left:19px;background:#f5fff6}.footnote{font-size:10px;color:#96a7a0;padding:15px 18px;border-top:1px solid #313b38}.secondary{background:transparent;border:1px solid #58655f;color:#d1ded6;padding:9px 12px;font-size:11px;letter-spacing:.05em}.primary{background:#bcd8c4;border:1px solid #bcd8c4;color:#112117;padding:9px 12px;font-weight:700;font-size:11px;letter-spacing:.03em}.primary:hover{background:#d2e9d9}.secondary:hover{border-color:#a2c8b0}.panel-body{padding:17px 18px}.casehead{display:flex;align-items:start;justify-content:space-between;gap:10px;margin-bottom:14px}.casehead h2{font-size:24px;font-weight:560;letter-spacing:-.035em;margin:0 0 5px}.casehead p{color:#a5b0aa;font-size:12px;max-width:680px;margin:0}select{background:#202828;border:1px solid #51615a;color:#e0eee5;padding:8px;max-width:250px;min-width:170px}#steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:7px;margin:20px 0 16px}.step{background:#202727;border:1px solid #3a4842;padding:12px 11px;min-height:115px;position:relative}.step-num{font-size:10px;color:#8faaa0}.step-kind{font-size:13px;font-weight:650;margin:9px 0}.step-status{text-transform:uppercase;letter-spacing:.11em;font-weight:800;font-size:9px;color:#bdcabf}.step.blocked{border-color:#98755f;background:#302723}.step.blocked .step-status{color:#efc79e}.step.allowed{border-color:#4c6658}.step.allowed .step-status{color:#b4d8bd}.step.observed .step-status{color:#a5b9b6}.outline{display:grid;grid-template-columns:1fr 1fr;gap:10px}.note{border-top:1px solid #33413a;padding-top:12px}.note b{display:block;margin-bottom:5px;font-size:11px}.note p{font-size:11px;color:#a7b4aa;margin:0}.set{font-size:11px;margin-top:8px;background:#25322d;padding:7px 8px;display:inline-block;color:#c6e6d0}.cols{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:13px}.axis{height:280px;width:100%;margin:12px 0}.frontier-list{max-height:330px;overflow:auto;padding:4px 12px}.frontier-row{display:grid;grid-template-columns:1.3fr .7fr .7fr;gap:7px;align-items:center;border-bottom:1px solid #2d3733;padding:12px 4px;font-size:11px}.frontier-row b{color:#d8e6da}.frontier-row button{background:transparent;color:#bddbc8;border:0;text-decoration:underline;text-align:left;padding:0}.accent-line{border-left:2px solid #a1cfb5;padding-left:13px;color:#b8c6ba;margin:13px 0}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px;overflow-wrap:anywhere;color:#b4d7be}.readout{background:#111716;border:1px solid #3a4842;padding:14px;margin:12px 0}.actions{display:flex;gap:9px;flex-wrap:wrap}.field{display:flex;align-items:center;gap:12px;margin:18px 0;font-size:12px}.field input{flex:1;min-width:50px;accent-color:#b9d6c2}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:350px;overflow:auto;background:#111716;padding:15px;color:#b7c7ba;font-size:10px;border:1px solid #33413a}footer{display:flex;justify-content:space-between;gap:16px;color:#6f8278;font-size:10px;letter-spacing:.02em;margin-top:19px}.hidden{display:none!important}.status-message{color:#e7c68e;font-size:11px;min-height:17px}.error{color:#ffafa8}.warn{color:#eacb8b}.ok{color:#b8d8c0}@media(max-width:950px){.content-grid,.cols{grid-template-columns:1fr}.hero{align-items:start}.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:550px){.shell{padding:16px}.pill{display:none}.hero h1{font-size:38px}.topright{font-size:9px}.casehead,.outline{display:block}.casehead select{width:100%;max-width:unset;margin-top:14px}footer{display:block}.metrics{gap:7px}.metric{padding:12px}.metric .val{font-size:26px}}
</style></head><body><div class="shell">
<header class="top"><div class="brand">QIRA <span>/ EVENT HORIZON</span></div><div class="topright"><span class="pulse"></span> EDGE SIMULATOR <span>R&D / 001</span></div></header>
<div class="hero"><div><div class="kicker">Counterfactual security observatory</div><h1>What actually <em>stops the loss?</em></h1><p>Explore hypothetical incident paths, intervene on the defender's controls, and expose the operational price of prevention. A simulation lab, not a live attack feed.</p></div><div class="pill">FICTIONAL DATA ONLY</div></div>
<nav class="tabs" aria-label="Research views"><button class="tab active" data-tab="observatory">01 / Observatory</button><button class="tab" data-tab="frontier">02 / Control Frontier</button><button class="tab" data-tab="robustness">03 / Uncertainty Lab</button><button class="tab" data-tab="proof">04 / Evidence Receipt</button></nav>
<div class="metrics"><div class="metric"><div class="label">Unprotected harm</div><div class="val" id="metric-base">—</div><div class="hint">Modeled impact units</div></div><div class="metric"><div class="label">Residual harm</div><div class="val rose" id="metric-risk">—</div><div class="hint">Across fictional adversarial cases</div></div><div class="metric"><div class="label">Prevention effect</div><div class="val accent" id="metric-prevent">—</div><div class="hint">Baseline minus residual harm</div></div><div class="metric"><div class="label">Legitimate friction</div><div class="val amber" id="metric-friction">—</div><div class="hint">Model-defined effort points</div></div></div>
<section class="content-grid" id="observatory">
<aside class="panel"><div class="panel-header"><span class="panel-title">Defender control plane</span><span class="small muted" id="active-count">0 enabled</span></div><div id="controls" class="controls"></div><div class="footnote">These policies modify the simulated environment only. No real identity provider, network, or customer data is accessed.<div class="actions" style="margin-top:13px"><button class="secondary" id="reset">Reset</button><button class="primary" id="all-controls">Enable all</button></div></div></aside>
<div class="panel"><div class="panel-header"><span class="panel-title">One scenario / two worlds</span><span class="small muted" id="case-kind">SELECT A CASE</span></div><div class="panel-body">
<div class="casehead"><div><h2 id="case-title">Loading scenario</h2><p id="case-desc"></p></div><select aria-label="Choose fictional scenario" id="scenario"></select></div>
<div class="kicker">Sequential decision trace / after controls</div><div id="steps"></div><div class="outline"><div class="note"><b>Counterfactual difference</b><p id="difference">—</p></div><div class="note"><b>Minimal modeled stopping controls</b><div id="minimal"><span class="muted">—</span></div></div></div>
</div></div></section>
<section class="cols hidden" id="frontier"><div class="panel"><div class="panel-header"><span class="panel-title">Policy frontier</span><span class="small muted">All 32 combinations tested</span></div><div class="panel-body"><p class="muted small">Each point is one defensive policy. Lower and further left is better. Dominance is calculated across harm, friction, and control complexity. This is a toy structural model.</p><svg class="axis" viewBox="0 0 550 285" role="img" aria-label="Pareto frontier scatter chart" id="scatter"></svg><div class="kicker">HORIZONTAL / legitimate friction &nbsp;&nbsp; VERTICAL / residual harm</div></div></div><div class="panel"><div class="panel-header"><span class="panel-title">Choose a portfolio</span><span class="small muted" id="frontier-count"></span></div><div class="panel-body"><div class="field"><label for="riskWeight">Prevention priority</label><input type="range" min="0" max="100" step="5" id="riskWeight" value="70"><span id="riskValue" class="mono">70%</span></div><div class="accent-line" id="portfolio-recommendation">Select the policy you want to compare.</div></div><div class="frontier-list" id="frontier-list"></div></div></section>
<section class="cols hidden" id="robustness">
<div class="panel"><div class="panel-header"><span class="panel-title">Uncertainty worlds</span><span class="small muted">Six deliberate assumption failures</span></div>
<div class="panel-body"><div class="kicker">What if the defense model is wrong?</div>
<h2 style="font-size:27px;letter-spacing:-.04em;font-weight:550">Stress your assumptions.</h2>
<p class="muted small">We disable fictional controls and challenge approval metadata. We do not assign real probabilities to these failures, and this is not an attacker playbook.</p>
<div class="frontier-list" id="robust-worlds" style="padding:0;max-height:370px"></div></div></div>
<div class="panel"><div class="panel-header"><span class="panel-title">Minimax-regret policy</span><span class="small muted">32 × 6 simulations</span></div>
<div class="panel-body">
<div class="kicker">Selected policy / worst-case harm</div><div class="val" style="font-size:35px;letter-spacing:-.04em" id="robust-current">—</div>
<div class="small muted" id="robust-explain" style="margin:14px 0 23px"></div>
<div class="kicker">Least worst regret under declared assumptions</div><div class="val accent" style="font-size:35px;letter-spacing:-.04em" id="robust-best">—</div>
<p class="small muted" id="robust-description"></p>
<button class="primary" id="apply-robust">Apply minimax portfolio</button>
<div class="readout small warn">A good synthetic minimax policy is not an empirically validated defense. No results here estimate the actual probability of compromise.</div>
</div></div></section>
<section class="cols hidden" id="proof"><div class="panel"><div class="panel-header"><span class="panel-title">Tamper-evident result receipt</span><span class="small muted">SHA-256 / deterministic payload</span></div><div class="panel-body"><p class="muted small">The SHA-256 covers the returned scenario, intervention settings, results and model disclaimer. It verifies bytes have not changed; it does <strong>not</strong> prove the simulation is correct or that Cloudflare witnessed an actual incident.</p><div class="readout"><span class="kicker">Current digest</span><div class="mono" id="digest">—</div></div><div class="actions"><button class="primary" id="verify">Verify in browser</button><button class="secondary" id="download">Save JSON receipt</button><button class="secondary" id="copy">Copy digest</button></div><p class="status-message" id="receipt-status"></p></div></div><div class="panel"><div class="panel-header"><span class="panel-title">Evidence and limitations</span></div><div class="panel-body"><p class="small muted">Provenance claims must survive independent testing. In this public version, scenario assumptions are authored, not inferred. Interventions are deterministic changes to those assumptions; they are not causal estimates learned from real environments.</p><p class="small muted">An approved insider export intentionally remains harmful under every modeled control. A defender that claims total prevention from this toy data is incorrect.</p><pre id="receipt-preview">Waiting for simulation…</pre></div></div></section>
<footer><span>QIRA LAB / EXPERIMENTAL / NO REAL CUSTOMER TELEMETRY</span><span>Deterministic structural counterfactuals ≠ demonstrated causal effects</span></footer><p class="status-message" id="status"></p>
</div><script nonce="__NONCE__">
(function(){
"use strict";
const $=id=>document.getElementById(id);
const state={meta:null,policy:{},scenarioId:"credential-cascade",report:null,tab:"observatory",riskWeight:70,requestId:0};
let currentReceipt=null, recommended=null;
const names={auth_failure:"Auth failure",login:"Session login",token_use:"Token accepted",grant:"Privilege grant",export:"Data export",read:"Normal read"};
function el(tag,className,txt){const v=document.createElement(tag);if(className)v.className=className;if(txt!==undefined)v.textContent=String(txt);return v;}
function tab(name){state.tab=name;for(const id of ["observatory","frontier","robustness","proof"])$(id).classList.toggle("hidden",id!==name);
 document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===name));}
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>tab(b.dataset.tab)));
function renderControls(){const wrap=$("controls");wrap.replaceChildren();for(const c of state.meta.controls){
 const row=el("label","control");const left=el("div");left.append(el("div","ctitle",c.name),el("div","csub",c.short));
 const input=el("input","switch");input.type="checkbox";input.checked=Boolean(state.policy[c.id]);input.setAttribute("aria-label",c.name);
 input.addEventListener("change",()=>{state.policy[c.id]=input.checked;run();});row.append(left,input);wrap.append(row);}
 $("active-count").textContent=Object.values(state.policy).filter(Boolean).length+" enabled";
}
function renderSelect(){const list=$("scenario");list.replaceChildren();for(const c of state.meta.scenarios){
 const option=el("option",null,c.name+(c.category==="benign"?" / benign":" / simulated attack"));option.value=c.id;list.append(option);}
 list.value=state.scenarioId;list.addEventListener("change",()=>{state.scenarioId=list.value;run();});}
function putMetric(id,n){$(id).textContent=Number(n).toLocaleString("en-US",{maximumFractionDigits:1});}
function renderCase(){
 const r=state.report,caseData=r.selected.scenario,chosen=r.selected.current,baseline=r.selected.baseline;
 $("case-title").textContent=caseData.name;$("case-desc").textContent=caseData.description;$("case-kind").textContent=caseData.category.toUpperCase();
 const wrap=$("steps");wrap.replaceChildren();
 chosen.trace.forEach(x=>{const card=el("div","step "+x.result);card.append(el("div","step-num","T + "+x.at+"s  ·  "+(x.index+1)),
  el("div","step-kind",names[x.kind]||x.kind),el("div","step-status",x.result),el("div","csub",x.why));wrap.append(card);});
 $("difference").textContent=caseData.category==="benign"
 ? ("Baseline operational friction: "+baseline.operationalFriction+"; selected: "+chosen.operationalFriction+
    ". Legitimate operations blocked: "+chosen.legitimateBlocked+".")
 : ("Baseline modeled harm: "+baseline.harm+" units; selected: "+chosen.harm+
    ". Hypothetically avoided: "+(baseline.harm-chosen.harm)+" units. No real-world guarantee.");
 const min=$("minimal");min.replaceChildren();
 if(caseData.category==="benign")min.append(el("p","small muted","This case measures the cost imposed on legitimate activity."));
 else if(!r.selected.minimalInterventions.length)min.append(el("p","small warn","None. This scenario persists under every modeled control."));
 else{for(const m of r.selected.minimalInterventions){
 const labels=m.controls.map(id=>state.meta.controls.find(c=>c.id===id).name).join(" + ");
 min.append(el("span","set",labels));min.append(document.createTextNode(" "));
 }}
}
function scatter(){
 const svg=$("scatter");while(svg.firstChild)svg.firstChild.remove();
 const all=state.report.frontier, maxF=Math.max(3,...all.map(x=>x.friction))*1.13,maxH=Math.max(100,state.report.summary.baselineHarm)*1.08;
 const mk=(tag,attrs)=>{const e=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const k in attrs)e.setAttribute(k,String(attrs[k]));svg.appendChild(e);return e;};
 for(let i=0;i<=4;i++){const x=42+i*115,y=247-i*54;mk("line",{x1:42,y1:y,x2:514,y2:y,stroke:"#314039", "stroke-width":1});
 const t=mk("text",{x:4,y:y+4,fill:"#83978d","font-size":11});t.textContent=String(Math.round(maxH*i/4));
 if(i>0)mk("line",{x1:x,y1:26,x2:x,y2:247,stroke:"#29342f","stroke-width":1});
 const b=mk("text",{x:x-5,y:267,fill:"#83978d","font-size":10});b.textContent=String(Math.round(maxF*i/4));}
 const selected=state.report.policyMask;
 for(const p of all){const x=42+(p.friction/maxF)*470,y=247-(p.harm/maxH)*221;
 const c=mk("circle",{cx:x,cy:y,r:p.mask===selected?8:5,fill:p.mask===selected?"#efcb94":"#a4d1b7",stroke:"#14201b","stroke-width":2});
 const title=document.createElementNS("http://www.w3.org/2000/svg","title");title.textContent=p.controls.join(", ")+" — harm "+p.harm+"; friction "+p.friction;c.appendChild(title);
 c.style.cursor="pointer";c.addEventListener("click",()=>applyMask(p.mask));}
}
function weightedScore(p){const r=state.riskWeight/100;return p.harm*r*3+p.friction*(1-r)*18+p.complexity*2;}
function recommend(){
 const list=state.report.frontier;recommended=[...list].sort((a,b)=>weightedScore(a)-weightedScore(b))[0];
 $("riskValue").textContent=state.riskWeight+"%";$("frontier-count").textContent=list.length+" nondominated policies";
 $("portfolio-recommendation").textContent="Illustrative lowest weighted score at "+state.riskWeight+"% prevention priority: "+(recommended.controls.length?recommended.controls.map(id=>state.meta.controls.find(c=>c.id===id).name).join(", "):"No controls")+"; "+recommended.harm+" residual units / "+recommended.friction+" friction points.";
 const wrap=$("frontier-list");wrap.replaceChildren();
 [...list].sort((a,b)=>weightedScore(a)-weightedScore(b)).forEach(p=>{
 const row=el("div","frontier-row"),btn=el("button",null,(p.controls.length?p.controls.length+" controls":"None")+" / Apply");
 btn.addEventListener("click",()=>applyMask(p.mask));row.append(btn,el("b",null,p.harm+" harm"),el("span",null,p.friction+" friction"));wrap.append(row);});
}
function applyMask(mask){state.meta.controls.forEach((c,i)=>{state.policy[c.id]=Boolean(mask&(1<<i));});renderControls();run();tab("observatory");}
async function digest(obj){const bytes=new TextEncoder().encode(JSON.stringify(obj));const hash=await crypto.subtle.digest("SHA-256",bytes);
 return Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,"0")).join("");}
function renderRobustness(){if(!state.report||!state.report.robustness)return;
 const r=state.report.robustness;const wrap=$("robust-worlds");wrap.replaceChildren();
 for(const world of r.selected.worldOutcomes){const row=el("div","frontier-row");
 const name=el("span","small",world.label);name.title=world.assumptions;
 row.append(name,el("b",null,world.harm+" harm"),el("span",null,world.friction+" friction"));wrap.append(row);}
 $("robust-current").textContent=r.selected.worstCaseHarm+" units";
 $("robust-best").textContent=r.minimax.worstCaseHarm+" units";
 $("robust-explain").textContent="Current worst scenario: "+r.selected.worstCaseHarm+" modeled harm units; maximum cross-world regret: "+r.selected.maxRegret+".";
 $("robust-description").textContent="Least worst-regret portfolio: "+(r.minimax.controls.length?r.minimax.controls.map(id=>state.meta.controls.find(x=>x.id===id).name).join(", "):"No controls")+". Maximum modeled regret: "+r.minimax.maxRegret+".";
}
function renderProof(){if(!currentReceipt)return;$("digest").textContent=currentReceipt.receipt.digest;
 $("receipt-preview").textContent=JSON.stringify({schema:currentReceipt.schema,selected:currentReceipt.selected.scenario.id,policy:currentReceipt.policy,summary:currentReceipt.summary,receipt:currentReceipt.receipt},null,2);}
async function run(){
 if(!state.meta)return;const runid=++state.requestId;$("status").textContent="Running deterministic counterfactuals…";
 try{const response=await fetch("/api/evaluate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({scenarioId:state.scenarioId,policy:state.policy})});
 if(!response.ok)throw new Error("Evaluation request failed ("+response.status+")");
 const data=await response.json();if(runid!==state.requestId)return;
 currentReceipt=data;state.report=data;renderControls();
 putMetric("metric-base",data.summary.baselineHarm);putMetric("metric-risk",data.summary.harm);
 putMetric("metric-prevent",data.summary.preventedHarm);putMetric("metric-friction",data.summary.friction);
 renderCase();scatter();recommend();renderRobustness();renderProof();$("status").textContent="Model evaluated. All figures are fictional utility units, not forecasts."; }
 catch(error){if(runid===state.requestId)$("status").textContent=error.message;}
}
$("reset").addEventListener("click",()=>{state.policy={};renderControls();run();});
$("all-controls").addEventListener("click",()=>{for(const c of state.meta.controls)state.policy[c.id]=true;renderControls();run();});
$("apply-robust").addEventListener("click",()=>{if(state.report?.robustness)applyMask(state.report.robustness.minimax.mask);});
$("riskWeight").addEventListener("input",e=>{state.riskWeight=Number(e.target.value);if(state.report)recommend();});
$("verify").addEventListener("click",async()=>{if(!currentReceipt)return;const {receipt,...payload}=currentReceipt;
 const computed=await digest(payload);const good=computed===receipt.digest;$("receipt-status").textContent=good?"SHA-256 matches this downloaded model output. Authenticity and assumptions remain unverified.":"Digest mismatch — results modified."; $("receipt-status").className="status-message "+(good?"ok":"error");});
$("download").addEventListener("click",()=>{if(!currentReceipt)return;const blob=new Blob([JSON.stringify(currentReceipt,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob);
 const a=document.createElement("a");a.href=url;a.download="qira-event-horizon-"+state.scenarioId+"-receipt.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),500);});
$("copy").addEventListener("click",async()=>{if(!currentReceipt)return;try{await navigator.clipboard.writeText(currentReceipt.receipt.digest);$("receipt-status").textContent="Digest copied.";}catch{$("receipt-status").textContent="Clipboard unavailable; select the digest above to copy."; }});
(async()=>{try{const r=await fetch("/api/meta");if(!r.ok)throw Error("Unable to load scenarios");
 state.meta=await r.json();renderSelect();renderControls();await run();}catch(e){$("status").textContent=e.message;}})();
})();
</script></body></html>`;
}

async function sha256Json(payload){
 const bytes=new TextEncoder().encode(JSON.stringify(payload));
 const digest=await crypto.subtle.digest("SHA-256",bytes);
 return Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
}

function jsonResponse(data,status=200){
 return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"}});
}

async function fetchHandler(request){
 const url=new URL(request.url);
 try{
 if(url.pathname==="/health"&&request.method==="GET"){
  return jsonResponse({ok:true,service:"Qira Event Horizon",version:"synthetic-v1",data:"fictional",mode:"read-only",persistence:false});
 }
 if(url.pathname==="/api/meta"&&request.method==="GET"){
  return jsonResponse({schema:"qira-event-horizon/meta-v1",controls:CONTROL_INFO,scenarios:SCENARIOS.map(s=>({id:s.id,name:s.name,description:s.description,category:s.category})),notice:"No real events or user accounts; fictional decision model"});
 }
 if(url.pathname==="/api/evaluate"&&request.method==="POST"){
  const type=request.headers.get("Content-Type")||"";if(!type.toLowerCase().startsWith("application/json"))return jsonResponse({error:"Expected application/json"},415);
  if(Number(request.headers.get("Content-Length")||0)>4096)return jsonResponse({error:"Payload exceeds 4KB"},413);
  const raw=await request.text();if(raw.length>4096)return jsonResponse({error:"Payload exceeds 4KB"},413);
  let body;try{body=JSON.parse(raw);}catch{return jsonResponse({error:"Malformed JSON"},400);}
  if(!body||typeof body!=="object"||Array.isArray(body)||Object.keys(body).some(k=>k!=="scenarioId"&&k!=="policy"))return jsonResponse({error:"Unknown request shape"},400);
  if(typeof body.scenarioId!=="string"||body.scenarioId.length>80)return jsonResponse({error:"Invalid scenarioId"},400);
  let payload;try{payload={...evaluate(body.policy||{},body.scenarioId),robustness:robustAnalysis(body.policy||{})};}catch(e){return jsonResponse({error:e.message},400);}
  const digest=await sha256Json(payload);
  return jsonResponse({...payload,receipt:{algorithm:"SHA-256",digest,meaning:"Integrity of returned synthetic policy model result only"}});
 }
 if(url.pathname==="/"&&request.method==="GET"){
  const nonce=btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16))));
  const csp="default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; script-src 'nonce-"+nonce+"'; style-src 'nonce-"+nonce+"'; connect-src 'self'; img-src 'none'; object-src 'none'";
  return new Response(renderPage(nonce).replaceAll("__NONCE__",nonce),{headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"public, max-age=120","Content-Security-Policy":csp,"X-Frame-Options":"DENY","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"}});
 }
 return jsonResponse({error:"Not found"},404);
 }catch(err){return jsonResponse({error:"Internal evaluation error"},500);}
}

export default { fetch: fetchHandler };