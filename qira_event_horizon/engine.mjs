// Qira Event Horizon, synthetic-only policy simulator. No network or exploitation.

export const CONTROL_INFO=[{"id":"mfa","name":"Phishing-resistant MFA","short":"Identity checkpoint","cost":"Requires an identity challenge for interactive sessions"},{"id":"bound_tokens","name":"Token binding","short":"Constrain bearer replay","cost":"Requires sender-constrained service tokens"},{"id":"grant_review","name":"Privilege review","short":"Approval before elevation","cost":"Introduces approval latency for legitimate elevation"},{"id":"export_approval","name":"Export approval","short":"Review sensitive exports","cost":"Adds friction to approved export operations"},{"id":"quarantine","name":"Adaptive quarantine","short":"Lock after auth failures","cost":"Can mistakenly block legitimate account recovery"}];

export const SCENARIOS=[{"id":"credential-cascade","name":"Credential cascade","category":"malicious","description":"Fictional stolen credentials lead to elevation and an unapproved export.","weight":1,"events":[{"at":0,"kind":"login","credential":"stolen"},{"at":12,"kind":"grant","approved":false},{"at":40,"kind":"export","approved":false}]},{"id":"partner-replay","name":"Partner token replay","category":"malicious","description":"A copied partner token provides elevated access to a protected dataset.","weight":1,"events":[{"at":0,"kind":"token_use","credential":"stolen","scope":"admin"},{"at":25,"kind":"export","approved":false}]},{"id":"slow-and-quiet","name":"Low-and-slow privilege abuse","category":"malicious","description":"Slow failed logins followed by a compromised session. Burst-based quarantine misses the sequence.","weight":1,"events":[{"at":0,"kind":"auth_failure"},{"at":600,"kind":"auth_failure"},{"at":1200,"kind":"auth_failure"},{"at":1810,"kind":"login","credential":"stolen"},{"at":1870,"kind":"grant","approved":false},{"at":1950,"kind":"export","approved":false}]},{"id":"insider-override","name":"Trusted insider misuse","category":"malicious","description":"An authorized insider makes a properly approved export for an illegitimate purpose. Authentication controls cannot infer intent.","weight":1,"events":[{"at":0,"kind":"login","credential":"legitimate"},{"at":25,"kind":"grant","approved":true},{"at":60,"kind":"export","approved":true}]},{"id":"supply-chain-key","name":"Compromised integration key","category":"malicious","description":"A stolen service token is replayed into a privileged integration route.","weight":1,"events":[{"at":0,"kind":"token_use","credential":"stolen","scope":"admin"},{"at":34,"kind":"export","approved":false}]},{"id":"ordinary-day","name":"Routine business session","category":"benign","description":"A regular employee signs in and reads permitted records.","weight":1,"events":[{"at":0,"kind":"login","credential":"legitimate"},{"at":40,"kind":"read"},{"at":120,"kind":"read"}]},{"id":"admin-maintenance","name":"Scheduled migration","category":"benign","description":"Approved admin work including a legitimate export should continue.","weight":1,"events":[{"at":0,"kind":"login","credential":"legitimate"},{"at":25,"kind":"grant","approved":true},{"at":75,"kind":"export","approved":true}]},{"id":"legitimate-service","name":"Trusted backup service","category":"benign","description":"Authorized service token retrieves an approved backup.","weight":1,"events":[{"at":0,"kind":"token_use","credential":"legitimate","scope":"admin"},{"at":32,"kind":"export","approved":true}]},{"id":"account-recovery","name":"Legitimate account recovery","category":"benign","description":"An employee mistypes credentials repeatedly before signing in.","weight":1,"events":[{"at":0,"kind":"auth_failure"},{"at":22,"kind":"auth_failure"},{"at":46,"kind":"auth_failure"},{"at":70,"kind":"auth_failure"},{"at":93,"kind":"login","credential":"legitimate"},{"at":115,"kind":"read"}]}];

function normalizePolicy(input){
 if(!input||typeof input!=="object"||Array.isArray(input))throw new Error("Policy must be an object");
 if(Object.keys(input).some(k=>!CONTROL_INFO.some(c=>c.id===k)))throw new Error("Unknown defensive control");
 const p={};for(const c of CONTROL_INFO){const value=input[c.id]??false;if(typeof value!=="boolean")throw new Error("Controls must be booleans");p[c.id]=value;}return p;
}

function simulate(scenario, policy){
 const p=normalizePolicy(policy);
 const trace=[];let session=false,privileged=false,failures=[],quarantineUntil=-1,maliciousExports=0,blockedLegitimate=0,operationalFriction=0,privilegedCompromise=false,successfulReads=0;
 for(let i=0;i<scenario.events.length;i++){
  const e=scenario.events[i];let result="allowed",why="",friction=0;
  if(e.kind==="auth_failure"){failures=failures.filter(t=>e.at-t<=300);failures.push(e.at);result="observed";why="Failed authentication recorded";
    if(p.quarantine&&failures.length>=3){quarantineUntil=e.at+900;why="Quarantine engaged after three failures";}
  }else if(e.kind==="login"){
    if(p.quarantine&&e.at<quarantineUntil){result="blocked";why="Account held by adaptive quarantine";}
    else if(p.mfa&&e.credential==="stolen"){result="blocked";why="Stolen credential cannot complete required MFA";}
    else{session=true;privileged=false;why="Interactive session established";if(p.mfa){friction=1;why+=" after MFA";}}
  }else if(e.kind==="token_use"){
    if(p.bound_tokens&&e.credential==="stolen"){result="blocked";why="Sender-constrained token rejects replay";}
    else{session=true;privileged=e.scope==="admin";why="Service token accepted";if(p.bound_tokens)friction=0.4;}
  }else if(e.kind==="grant"){
    if(!session){result="blocked";why="No authenticated session";}
    else if(p.grant_review&&!e.approved){result="blocked";why="Privilege elevation lacks independent approval";}
    else{privileged=true;why="Privilege elevation allowed";if(p.grant_review)friction=2;}
  }else if(e.kind==="export"){
    if(!session||!privileged){result="blocked";why="Privileged session not established";}
    else if(p.export_approval&&!e.approved){result="blocked";why="Sensitive export rejected without approval";}
    else{why="Export permitted by modeled controls";if(p.export_approval)friction=1;
      if(scenario.category==="malicious")maliciousExports++;}
  }else if(e.kind==="read"){
    if(!session){result="blocked";why="Read requires an authenticated session";}
    else{why="Permitted read";successfulReads++;}
  }else throw new Error("Unknown synthetic event");
  if(scenario.category==="benign"&&result==="blocked"){blockedLegitimate++;operationalFriction+=5;}
  if(scenario.category==="benign")operationalFriction+=friction;
  if(scenario.category==="malicious"&&privileged)privilegedCompromise=true;
  trace.push({index:i,at:e.at,kind:e.kind,result,why,friction});
 }
 // 100 risk points per unwanted export, plus 15 for established privileged
 // access. These are arbitrary synthetic utility units, not money or probability.
 const harm=scenario.category==="malicious"?(maliciousExports*100+(privilegedCompromise?15:0)):0;
 return {id:scenario.id,name:scenario.name,category:scenario.category,harm,
  unwantedExports:maliciousExports,legitimateBlocked:blockedLegitimate,
  operationalFriction:Number(operationalFriction.toFixed(2)),trace};
}

function compareAll(policy){
 const p=normalizePolicy(policy);const scenarios=SCENARIOS.map(s=>simulate(s,p));
 const baseline=SCENARIOS.map(s=>simulate(s,normalizePolicy({})));
 const harmful=scenarios.filter(s=>s.category==="malicious");
 const original=baseline.filter(s=>s.category==="malicious");
 const totalHarm=harmful.reduce((a,b)=>a+b.harm,0);
 const baselineHarm=original.reduce((a,b)=>a+b.harm,0);
 const friction=scenarios.reduce((a,b)=>a+b.operationalFriction,0);
 const legitimateBlocked=scenarios.reduce((a,b)=>a+b.legitimateBlocked,0);
 const complexity=CONTROL_INFO.filter(c=>p[c.id]).length;
 return {policy:p,scenarios,baseline,summary:{
  harm:totalHarm,baselineHarm,preventedHarm:baselineHarm-totalHarm,
  friction:Number(friction.toFixed(2)),legitimateBlocked,complexity,
  simulatedCases:SCENARIOS.length,unwantedExports:harmful.reduce((a,b)=>a+b.unwantedExports,0),
  title:"Synthetic counterfactual policy utility; not observed outcomes"}};
}

function maskToPolicy(mask){const p={};CONTROL_INFO.forEach((c,i)=>p[c.id]=Boolean(mask&(1<<i)));return p;}

function controlsEnabled(p){return CONTROL_INFO.filter(c=>p[c.id]).map(c=>c.id);}

function pareto(){
 const portfolios=[];for(let mask=0;mask<1<<CONTROL_INFO.length;mask++){
  const r=compareAll(maskToPolicy(mask));portfolios.push({mask,controls:controlsEnabled(r.policy),...r.summary});
 }
 const frontier=portfolios.filter(p=>!portfolios.some(q=>
  q!==p&&q.harm<=p.harm&&q.friction<=p.friction&&q.complexity<=p.complexity&&
  (q.harm<p.harm||q.friction<p.friction||q.complexity<p.complexity)));
 const sorted=frontier.sort((a,b)=>a.harm-b.harm||a.friction-b.friction||a.complexity-b.complexity);
 return {all:portfolios,frontier:sorted};
}

function minimalInterventions(scenario){
 if(scenario.category!=="malicious")return[];
 const candidates=[];
 for(let mask=1;mask<1<<CONTROL_INFO.length;mask++){
  const p=maskToPolicy(mask);const r=simulate(scenario,p);
  if(r.harm===0)candidates.push({mask,controls:controlsEnabled(p)});
 }
 return candidates.filter(a=>!candidates.some(b=>a.mask!==b.mask&&(a.mask&b.mask)===b.mask));
}

function evaluate(policy,scenarioId){
 const found=SCENARIOS.find(x=>x.id===scenarioId);
 if(!found)throw new Error("Unknown scenario identifier");
 const portfolio=compareAll(policy);const base=portfolio.baseline.find(x=>x.id===scenarioId);const chosen=portfolio.scenarios.find(x=>x.id===scenarioId);
 const matrix=pareto();const policyMask=CONTROL_INFO.reduce((m,c,i)=>m|(portfolio.policy[c.id]?(1<<i):0),0);
 return {schema:"qira-event-horizon/synthetic-v1",disclaimer:"Synthetic causal model, not evidence of real attacks or guaranteed prevention",
  policy:portfolio.policy,selected:{scenario:found,baseline:base,current:chosen,minimalInterventions:minimalInterventions(found)},
  summary:portfolio.summary,frontier:matrix.frontier,policyMask,engine:"deterministic hypothetical state machine v1"};
}

export { normalizePolicy,simulate,compareAll,maskToPolicy,pareto,minimalInterventions,evaluate };