import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {SCHEMA,proof,verifyProof,analyzeSnapshot} from "../core.mjs";
import {renderHumanReport} from "../report.mjs";
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const time="2026-11-16T06:00:00Z",hash="0123456789abcdef0123456789abcdef01234567";
const files=["stable.yml","canary.yml","manual.yml"];
const values=[true,true,"unknown"];
const facts=files.map((name,i)=>({
 provider:"github",asset:"org/repo:.github/workflows/"+name,signal:"workflow_token_write_permission",
 value:values[i],observed_at:time,source_url:"https://github.com/org/repo/blob/"+hash+"/.github/workflows/"+name+"#L15"
}));
test("write-level permission inventory is visible but never inflates findings",async()=>{
 const s={schema:SCHEMA,captured_at:time,facts};
 const result=analyzeSnapshot(s);
 assert.equal(result.counts.review,0);
 assert.equal(result.controls.length,0);
 const receipt=await proof(s);
 assert.equal(await verifyProof(receipt),true);
 const html=await renderHumanReport(receipt);
 assert.match(html,/Declared write-level permission inventory/);
 assert.match(html,/2 workflow\(s\) declare write-level permissions; 1 workflow\(s\) have unknown permission declarations/);
 for(const name of files)assert.match(html,new RegExp(name.replace(".","\\.")));
 assert.match(html,/not a vulnerability count/);
});
