import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync,writeFileSync,rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {run} from "./cloudflare_posture_cli.mjs";

const states=["http_request_firewall_managed","http_request_firewall_custom","http_ratelimit"];
function fixture(observed="2026-11-15T23:00:00Z"){
 return {schema:"qira-edge-inventory/v1",zone_alias:"fictional-sample",
  observed_at:observed,origin:"operator-exported-cloudflare-readonly",
  settings:{min_tls_version:"1.0",ssl:"full",always_use_https:"on",legacy_waf:"off"},
  entrypoints:{account:Object.fromEntries(states.map(x=>[x,"no_entrypoint"])),
               zone:Object.fromEntries(states.map(x=>[x,"no_entrypoint"]))},
  surface:{purpose:"public-synthetic-demo",access_application_present:false,worker_binding_count:0}};
}
function withFiles(fn){
 const temp=mkdtempSync(join(tmpdir(),"qira-evidence-"));
 try{
  const current=join(temp,"current.json"),previous=join(temp,"before.json");
  writeFileSync(current,JSON.stringify(fixture("2026-11-16T01:00:00Z")));
  writeFileSync(previous,JSON.stringify(fixture()));
  return fn({current,previous});
 }finally{rmSync(temp,{recursive:true,force:true});}
}
test("offline CLI returns seven evidence-backed checks without network use",()=>{
 withFiles(({current})=>{
  const report=run(["--current",current]);
  assert.equal(report.audit.findings.length,7);
  assert.equal(report.operational_mutations,0);
  assert.equal(report.network_requests,0);
  assert.equal(report.audit.source_origin_attested,false);
  assert.equal(report.drift,null);
 });
});
test("the CLI's independent process exits cleanly and never writes a report by default",()=>{
 withFiles(({current})=>{
  const command=fileURLToPath(new URL("./cloudflare_posture_cli.mjs",import.meta.url));
  const proc=spawnSync(process.execPath,[command,"--current",current],{encoding:"utf8"});
  assert.equal(proc.status,0,proc.stderr);
  const report=JSON.parse(proc.stdout);
  assert.equal(report.audit.schema,"qira-edge-posture-audit/v1");
  assert.equal(report.audit.zone_alias,"fictional-sample");
 });
});
test("two snapshots with changed TLS produce exactly one drift record",()=>{
 withFiles(({current,previous})=>{
  const report=run(["--previous",previous,"--current",current]);
  assert.equal(report.drift.change_count,0);
  const update=fixture("2026-11-16T01:00:00Z");
  update.settings.min_tls_version="1.2";
  writeFileSync(current,JSON.stringify(update));
  const changed=run(["--current",current,"--previous",previous]);
  assert.equal(changed.drift.change_count,1);
  assert.equal(changed.drift.changes[0].field,"settings.min_tls_version");
 });
});
test("CLI fails closed on arbitrary JSON with extra sensitive fields",()=>{
 withFiles(({current})=>{
  const s=fixture();s.authorization="Bearer fake";
  writeFileSync(current,JSON.stringify(s));
  assert.throws(()=>run(["--current",current]),/unexpected fields/);
 });
});
test("CLI refuses unrelated command-line flags and too-large files",()=>{
 withFiles(({current})=>{
  assert.throws(()=>run(["--upload",current]),/unexpected/i);
  assert.throws(()=>run(["--current",current,"--current",current]),/duplicate/i);
  writeFileSync(current," ".repeat(128100));
  assert.throws(()=>run(["--current",current]),/128KB/);
 });
});
