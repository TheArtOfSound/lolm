import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash} from "node:crypto";
import worker from "../commercial/landing.mjs";
import {REAL_CASE,renderRealCaseStudy,sourceUrl} from "../commercial/real_case.mjs";
import {scanWorkflowSyntax} from "../workflow_static.mjs";

const wf=readFileSync(new URL("./fixtures/lolm_public_daily_workflow_f970.yml",import.meta.url),"utf8");
const agent=readFileSync(new URL("./fixtures/lolm_public_daily_release_f970.py",import.meta.url),"utf8");
const blobSha=text=>createHash("sha1").update("blob "+Buffer.byteLength(text)+"\0").update(text).digest("hex");
const wfLines=wf.split("\n"),agentLines=agent.split("\n");
const span=(rows,start,end)=>rows.slice(start-1,end).join("\n");

test("case study fixtures match exact Git blob objects in pinned public LOLM commit",()=>{
 assert.equal(REAL_CASE.commit,"f9700d2e661640da4a8d0cf2bb9c046d77f8a06b");
 assert.equal(blobSha(wf),REAL_CASE.workflowBlob,"YAML fixture must match the independently retrieved Git blob SHA");
 assert.equal(blobSha(agent),REAL_CASE.controlBlob,"Python fixture must match the independently retrieved Git blob SHA");
 assert.equal(REAL_CASE.externalReview,false);
});

test("independent exact-line checks establish four declared write permissions",()=>{
 const excerpt=span(wfLines,18,22);
 for(const scope of ["contents","pull-requests","issues","id-token"])
  assert.match(excerpt,new RegExp("(^|\\n)  "+scope+": write(\\s|$)"));
 assert.equal(wfLines[17],"permissions:");
 assert.equal(REAL_CASE.observations[0].source[0].start,18);
 assert.equal(REAL_CASE.observations[0].source[0].end,22);
});

test("independent exact-line checks establish mutable action tags and conditional SSH bootstrap",()=>{
 const uses=span(wfLines,30,40);
 for(const name of ["checkout","setup-python","setup-node"])
  assert.ok(uses.includes("uses: actions/"+name+"@v7"),name);
 assert.equal(wfLines[31].trim(),"- uses: actions/checkout@v7");
 const host=span(wfLines,53,65);
 assert.match(host,/if \[ -n "\$DEPLOY_KEY" \]/);
 assert.match(host,/ssh-keyscan -H/);
 assert.match(host,/~\/\.ssh\/known_hosts/);
 assert.match(host,/\|\| true/);
 assert.equal(REAL_CASE.observations[1].source[0].start,30);
 assert.equal(REAL_CASE.observations[2].source[0].end,65);
});

test("current bounded Qira Proof scanner reproduces exactly the three workflow observations",()=>{
 const scan=scanWorkflowSyntax(wf);
 assert.deepEqual(scan.workflow_unpinned_actions,{value:true,line:32});
 assert.deepEqual(scan.runtime_ssh_keyscan,{value:true,line:62});
 assert.equal(scan.workflow_token_write_permission.value,true);
 assert.deepEqual(scan.writeScopes,[
  {scope:"contents",line:19},{scope:"pull-requests",line:20},
  {scope:"issues",line:21},{scope:"id-token",line:22}
 ]);
 assert.equal(scan.workflow_pull_request_target_trigger.value,false);
 assert.equal(REAL_CASE.observations.every(x=>x.mode==="scanner corroborated"),true);
});

test("release-control gate fallback is source-confirmed but not scanner output",()=>{
 const gate=span(agentLines,147,162);
 assert.match(gate,/run_cmd\(\["npm", "audit", "--json"\], cwd=CLIENT\)/);
 assert.match(gate,/data = json\.loads\(out\)/);
 assert.match(gate,/except Exception:\s*\n\s*# [^\n]+\n\s*high = 0/);
 assert.match(gate,/high == 0/);
 assert.doesNotMatch(gate,/if code\s*!=\s*0/);
 assert.equal(REAL_CASE.companion[0].mode,"manual source review only");
});

test("release-control merged result is not a required input to later publish/deploy gates",()=>{
 const merge=span(agentLines,172,184);
 assert.match(merge,/"gh", "pr", "merge", branch, "--squash", "--admin"/);
 const orchestration=span(agentLines,277,316);
 assert.match(orchestration,/merged = do_merge\(args\.allow_fire, branch, creds\)/);
 assert.match(orchestration,/if pg\.passed:\s*\n\s*canary_pub = do_publish/);
 assert.match(orchestration,/if args\.allow_fire and creds\["deploy"\]:/);
 const afterMerge=orchestration.slice(orchestration.indexOf("merged = do_merge"));
 assert.doesNotMatch(afterMerge,/if\s+(?:merged|merged\.get)\s*(?:\(|\[|:)/);
 assert.equal(REAL_CASE.companion[1].mode,"manual source review only");
});

test("all public source links use pinned SHA and bounded line anchors",()=>{
 const all=[...REAL_CASE.observations,...REAL_CASE.companion];
 assert.equal(all.length,5);
 for(const x of all)for(const s of x.source){
  const link=sourceUrl(s.path,s.start,s.end);
  assert.ok(link.startsWith("https://github.com/TheArtOfSound/lolm/blob/"+REAL_CASE.commit+"/"));
  assert.ok(link.endsWith("#L"+s.start+"-L"+s.end));
  const lines=s.path===REAL_CASE.workflow?wfLines:agentLines;
  assert.ok(s.start>0&&s.start<=s.end&&s.end<=lines.length);
 }
 const page=renderRealCaseStudy();
 for(const x of all)assert.ok(page.includes(x.id));
 assert.match(page,/public issue #72/);
 assert.match(page,/not current-state findings/);
 assert.match(page,/No external reviewer has yet adjudicated the results/);
});

test("live case study route accurately separates scanner observations and manual review",async()=>{
 const req=new Request("https://proof.imagineqira.com/case-study");
 const response=await worker.fetch(req);
 assert.equal(response.status,200);
 const html=await response.text();
 assert.match(html,/<title>Real GitHub Actions Security Findings: LOLM Case Study \| Qira Proof<\/title>/);
 assert.match(html,/Three observations corroborated against source/);
 assert.match(html,/Release-control defects found outside the scanner/);
 assert.match(html,/or an independent third-party audit/);
 assert.match(html,/No secrets, cloud credentials, branch protections/);
 assert.match(html,/QP-REAL-03/);
 assert.match(html,/QP-MANUAL-02/);
 assert.match(html,/f9700d2e6616/);
 assert.match(html,/https:\/\/github\.com\/TheArtOfSound\/lolm\/blob\/f9700d2e661640da4a8d0cf2bb9c046d77f8a06b/);
 assert.doesNotMatch(html,/<script>/);
 assert.doesNotMatch(html,/100% secure|all vulnerabilities found|confirmed compromise/i);
});

test("case study homepage integration preserves public purchase CTA, invoice and intake paths",async()=>{
 const link="https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07";
 const response=await worker.fetch(new Request("https://proof.imagineqira.com/"),{QIRA_PROOF_CHECKOUT_URL:link});
 assert.equal(response.status,200);
 const html=await response.text();
 assert.match(html,/An observation you can verify/);
 assert.match(html,/href="\/case-study"/);
 assert.match(html,/href="\/sample-report"/);
 assert.match(html,/id="buyLink"/);
 assert.match(html,/href="https:\/\/buy\.stripe\.com\/9B63cvexo0ts3OBfyv7kc07"/);
 const health=await worker.fetch(new Request("https://proof.imagineqira.com/health"),{QIRA_PROOF_CHECKOUT_URL:link});
 assert.equal((await health.json()).checkout_configured,true);
 const intake=await worker.fetch(new Request("https://proof.imagineqira.com/start-review"));
 assert.equal(intake.status,200);
});
