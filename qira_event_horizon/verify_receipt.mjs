#!/usr/bin/env node
/**
 * Offline verifier for a Qira Event Horizon *synthetic* receipt.
 *
 * Checks (1) SHA-256 byte integrity and (2) independent deterministic replay
 * using local reviewed source. This does NOT authenticate the Worker origin,
 * prove model assumptions, certify a live incident, or provide a signature.
 *
 * Usage: node qira_event_horizon/verify_receipt.mjs report.json
 */
import {readFileSync} from "node:fs";
import {createHash,timingSafeEqual} from "node:crypto";
import {pathToFileURL} from "node:url";
import {evaluate,normalizePolicy} from "./engine.mjs";
import {robustAnalysis} from "./robustness.mjs";

export function verifyReceipt(report){
 if(!report||typeof report!=="object"||Array.isArray(report))return {valid:false,reason:"Expected JSON object"};
 const {receipt,...payload}=report;
 if(!receipt||receipt.algorithm!=="SHA-256"||typeof receipt.digest!=="string"||!/^[0-9a-f]{64}$/.test(receipt.digest))
   return {valid:false,reason:"Invalid SHA-256 receipt"};
 const actual=createHash("sha256").update(JSON.stringify(payload)).digest("hex");
 if(!timingSafeEqual(Buffer.from(actual,"hex"),Buffer.from(receipt.digest,"hex")))
   return {valid:false,integrity:false,replayed:false,reason:"Payload digest differs from receipt"};
 if(payload.schema!=="qira-event-horizon/synthetic-v1"
    ||typeof payload.selected?.scenario?.id!=="string"
    ||payload.robustness?.schema!=="qira-event-horizon/assumption-robustness-v1")
   return {valid:false,integrity:true,replayed:false,reason:"Unsupported synthetic research schema"};
 try{
  const policy=normalizePolicy(payload.policy);
  const expected={...evaluate(policy,payload.selected.scenario.id),robustness:robustAnalysis(policy)};
  if(JSON.stringify(expected)!==JSON.stringify(payload))
    return {valid:false,integrity:true,replayed:false,reason:"Model replay does not match claimed result"};
 }catch(e){
  return {valid:false,integrity:true,replayed:false,reason:"Cannot replay: "+String(e.message).slice(0,130)};
 }
 return {valid:true,integrity:true,replayed:true,
    disclaimer:"Only consistent with local synthetic model; no actual incident or source authenticity verified"};
}

function main(){
 const filename=process.argv[2];
 if(!filename||process.argv.length!==3){
  process.stderr.write("Usage: node qira_event_horizon/verify_receipt.mjs <report.json>\n");process.exitCode=2;return;
 }
 try{
  const raw=readFileSync(filename,"utf8");
  if(Buffer.byteLength(raw)>2_000_000)throw new Error("Receipt exceeds 2MB limit");
  const result=verifyReceipt(JSON.parse(raw));
  process.stdout.write(JSON.stringify(result,null,2)+"\n");
  process.exitCode=result.valid?0:1;
 }catch(e){process.stderr.write("Unable to verify: "+String(e.message).slice(0,180)+"\n");process.exitCode=2;}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main();
