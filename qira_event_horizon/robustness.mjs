// Qira Event Horizon — stress test policy assumptions, not real attack execution.

import {CONTROL_INFO,SCENARIOS,normalizePolicy,simulate,maskToPolicy} from "./engine.mjs";

const WORLDS = [{"id":"nominal","label":"Nominal assumptions","disabled":[],"approvalFlip":false,"explanation":"All fictional controls operate as specified"},{"id":"identity-degraded","label":"MFA enforcement unavailable","disabled":["mfa"],"approvalFlip":false,"explanation":"Interactive MFA benefit unavailable under a modeled failure"},{"id":"token-degraded","label":"Sender constraint unavailable","disabled":["bound_tokens"],"approvalFlip":false,"explanation":"Service-token binding does not enforce under this hypothetical"},{"id":"export-degraded","label":"Export gate unavailable","disabled":["export_approval"],"approvalFlip":false,"explanation":"Approval gate is ineffective in the modeled environment"},{"id":"approval-unreliable","label":"Approval metadata untrusted","disabled":[],"approvalFlip":true,"explanation":"Malicious operations may carry seemingly valid approval flags; intent cannot be established by metadata"},{"id":"combined-degradation","label":"Multiple controls unavailable","disabled":["mfa","bound_tokens","export_approval"],"approvalFlip":false,"explanation":"Deliberately severe multi-control failure world"}];

function evaluateWorld(policy,world){
 const p=normalizePolicy(policy);const active={...p};for(const c of world.disabled)active[c]=false;
 let harm=0,friction=0,blocked=0;const cases=[];
 for(const s of SCENARIOS){
  const scenario=world.approvalFlip&&s.category==="malicious"
   ?{...s,events:s.events.map(e=>("approved" in e?{...e,approved:true}:e))}
   :s;
  const outcome=simulate(scenario,active);
  harm+=outcome.harm;friction+=outcome.operationalFriction;blocked+=outcome.legitimateBlocked;
  cases.push({id:s.id,harm:outcome.harm,blocked:outcome.legitimateBlocked});
 }
 return {world:world.id,label:world.label,harm,friction:Number(friction.toFixed(2)),blocked,assumptions:world.explanation,cases};
}

function robustAnalysis(policy){
 const active=normalizePolicy(policy);
 const portfolioMasks=Array.from({length:1<<CONTROL_INFO.length},(_,mask)=>mask);
 const portfolios=portfolioMasks.map(mask=>{
  const p=maskToPolicy(mask),worlds=WORLDS.map(w=>evaluateWorld(p,w));
  const complexity=CONTROL_INFO.filter(c=>p[c.id]).length;
  const utility=worlds.map(w=>w.harm+w.friction*4+complexity*3);
  return {mask,controls:CONTROL_INFO.filter(c=>p[c.id]).map(c=>c.id),
    bestCaseHarm:Math.min(...worlds.map(w=>w.harm)),worstCaseHarm:Math.max(...worlds.map(w=>w.harm)),
    meanHarm:Number((worlds.reduce((a,b)=>a+b.harm,0)/worlds.length).toFixed(2)),
    utility,worlds};
 });
 const worldMin=WORLDS.map((w,i)=>Math.min(...portfolios.map(p=>p.utility[i])));
 const rows=portfolios.map(p=>{
  const regrets=p.utility.map((value,i)=>value-worldMin[i]);
  return {...p,maxRegret:Math.max(...regrets),meanRegret:Number((regrets.reduce((a,b)=>a+b,0)/regrets.length).toFixed(2))};
 });
 const best=[...rows].sort((a,b)=>a.maxRegret-b.maxRegret||a.meanRegret-b.meanRegret||a.controls.length-b.controls.length)[0];
 const mask=CONTROL_INFO.reduce((n,c,i)=>n|(active[c.id]?(1<<i):0),0);
 const selected=rows.find(row=>row.mask===mask);
 return {schema:"qira-event-horizon/assumption-robustness-v1",
    methodology:"Deterministic minimax regret over six fictional worlds; exact enumeration of 32 policies; utility=harm+4*friction+3*enabledControls",
    validity:"Assumption stress-testing only, not a calibrated real-world likelihood model",
    worlds:WORLDS.map(x=>({id:x.id,label:x.label,explanation:x.explanation})),
    selected:{mask,controls:selected.controls,worstCaseHarm:selected.worstCaseHarm,meanHarm:selected.meanHarm,maxRegret:selected.maxRegret,worldOutcomes:selected.worlds},
    minimax:{mask:best.mask,controls:best.controls,worstCaseHarm:best.worstCaseHarm,meanHarm:best.meanHarm,maxRegret:best.maxRegret},
    controlCombinations:rows.length,
    caution:"No zero-risk guarantee; attacker adaptation and organizational context are not modeled"};
}

export { WORLDS, evaluateWorld, robustAnalysis };