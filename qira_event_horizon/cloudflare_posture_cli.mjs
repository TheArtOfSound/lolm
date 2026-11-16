#!/usr/bin/env node
/**
 * Offline/read-only security configuration inventory audit.
 *
 * Consumes an explicitly bounded, sanitized export from an authorized
 * Cloudflare account. Does NOT contact the API. Report hash verifies content
 * consistency, not collection source or time. No zone IDs or secret values.
 *
 * Usage:
 * node qira_event_horizon/cloudflare_posture_cli.mjs --current sanitized.json
 * node qira_event_horizon/cloudflare_posture_cli.mjs --current current.json --previous earlier.json
 */
import {readFileSync} from "node:fs";
import {pathToFileURL} from "node:url";
import {auditSnapshot,compareSnapshots} from "./cloudflare_posture.mjs";

export function run(argv){
 if(!Array.isArray(argv)||argv.length<2||argv.length>4)throw new Error("Usage: --current sanitized.json [--previous earlier.json]");
 const params={};
 for(let i=0;i<argv.length;i+=2){
   const k=argv[i],v=argv[i+1];
   if(!["--current","--previous"].includes(k)||typeof v!=="string"||v.startsWith("--")||params[k])
     throw new Error("Unexpected or duplicate argument");
   params[k]=v;
 }
 if(!params["--current"])throw new Error("--current is required");
 function read(path){
  const contents=readFileSync(path,"utf8");
  if(Buffer.byteLength(contents,"utf8")>128_000)throw new Error("Inventory exceeds 128KB safety limit");
  return JSON.parse(contents);
 }
 const current=read(params["--current"]),audit=auditSnapshot(current);
 const before=params["--previous"]?compareSnapshots(read(params["--previous"]),current):null;
 return {schema:"qira-cloudflare-evidence-report/v1",audit,drift:before,
   operational_mutations:0,network_requests:0,
   warning:"Operator-declared configuration observations are not authenticated Cloudflare API attestations or measured attack prevention."};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 try{process.stdout.write(JSON.stringify(run(process.argv.slice(2)),null,2)+"\n");}
 catch(e){process.stderr.write("Audit rejected: "+String(e.message).slice(0,200)+"\n");process.exitCode=2;}
}
