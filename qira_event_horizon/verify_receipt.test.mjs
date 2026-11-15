import test from "node:test";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {mkdtempSync,writeFileSync,rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";
import {verifyReceipt} from "./verify_receipt.mjs";
import {evaluate} from "./engine.mjs";
import {robustAnalysis} from "./robustness.mjs";

function synth(){
 const p={mfa:true,bound_tokens:true};
 const body={...evaluate(p,"credential-cascade"),robustness:robustAnalysis(p)};
 const digest=createHash("sha256").update(JSON.stringify(body)).digest("hex");
 return {...body,receipt:{algorithm:"SHA-256",digest,
  meaning:"Integrity of returned synthetic policy model result only"}};
}
test("offline independent receipt replay succeeds on current model",()=>{
 const x=verifyReceipt(synth());
 assert.equal(x.valid,true);
 assert.equal(x.replayed,true);
 assert.match(x.disclaimer,/no actual incident/);
});
test("hash catches a changed result",()=>{
 const report=synth();
 report.summary.harm=0;
 const r=verifyReceipt(report);
 assert.equal(r.valid,false);
 assert.equal(r.integrity,false);
});
test("even a forged matching hash cannot pass deterministic replay",()=>{
 const report=synth();
 report.summary.harm=0;
 const {receipt,...body}=report;
 receipt.digest=createHash("sha256").update(JSON.stringify(body)).digest("hex");
 const r=verifyReceipt(report);
 assert.equal(r.integrity,true);
 assert.equal(r.replayed,false);
});
test("unknown control and incompatible schema rejected",()=>{
 let report=synth();report.policy={...report.policy,allowRemoteCommands:true};
 const {receipt,...body}=report;receipt.digest=createHash("sha256").update(JSON.stringify(body)).digest("hex");
 assert.equal(verifyReceipt(report).valid,false);
 report=synth();report.schema="not-a-model";
 const item={...report};delete item.receipt;
 report.receipt.digest=createHash("sha256").update(JSON.stringify(item)).digest("hex");
 assert.equal(verifyReceipt(report).valid,false);
});
test("CLI accepts valid local JSON and rejects tampered files",()=>{
 const dir=mkdtempSync(join(tmpdir(),"event-horizon-"));
 try{
  const valid=join(dir,"valid.json"),invalid=join(dir,"bad.json");
  const report=synth();writeFileSync(valid,JSON.stringify(report));
  report.summary.harm=-100;writeFileSync(invalid,JSON.stringify(report));
  const script=fileURLToPath(new URL("./verify_receipt.mjs",import.meta.url));
  const good=spawnSync(process.execPath,[script,valid],{encoding:"utf8"});
  assert.equal(good.status,0,good.stderr);
  assert.equal(JSON.parse(good.stdout).replayed,true);
  const bad=spawnSync(process.execPath,[script,invalid],{encoding:"utf8"});
  assert.equal(bad.status,1);
 }finally{rmSync(dir,{force:true,recursive:true});}
});
