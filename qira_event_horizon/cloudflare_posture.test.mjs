import test from "node:test";
import assert from "node:assert/strict";
import {auditSnapshot,compareSnapshots,evidenceHash,validateSnapshot} from "./cloudflare_posture.mjs";

const phases=["http_request_firewall_managed","http_request_firewall_custom","http_ratelimit"];
function snapshot(opts={}){
 const states=Object.fromEntries(phases.map(name=>[name,"no_entrypoint"]));
 return {schema:"qira-edge-inventory/v1",zone_alias:"fictional-zone",
   observed_at:"2026-11-15T23:00:00Z",origin:"operator-exported-cloudflare-readonly",
   settings:{min_tls_version:"1.0",ssl:"full",always_use_https:"on",legacy_waf:"off"},
   entrypoints:{account:{...states},zone:{...states}},
   surface:{purpose:"public-synthetic-demo",access_application_present:false,worker_binding_count:0},
   ...opts};
}
const pick=(report,id)=>report.findings.find(x=>x.id===id);
test("legacy TLS and non-strict origin certificate produce action review, not made-up breach odds",()=>{
 const a=auditSnapshot(snapshot());
 assert.equal(a.findings.length,7);
 assert.equal(pick(a,"TLS_EDGE_MINIMUM").status,"review");
 assert.equal(pick(a,"ORIGIN_CERTIFICATE_VERIFICATION").status,"review");
 assert.equal(pick(a,"HTTPS_REDIRECT").status,"pass");
 assert.equal(pick(a,"PUBLIC_DEMO_ACCESS_BOUNDARY").status,"intentional_public");
 assert.equal(a.read_only,true);
 assert.equal(a.source_origin_attested,false);
 assert.equal(a.protection_claims_validated,false);
 assert.match(a.disclaimer,/not a penetration test/);
});
test("no WAF entrypoint must not be represented as no Cloudflare protection",()=>{
 const a=auditSnapshot(snapshot());
 const waf=pick(a,"MANAGED_WAF_EXECUTION");
 assert.equal(waf.status,"review");
 assert.match(waf.qualification,/not demonstrate absence of all Cloudflare default protections/i);
 assert.equal(pick(a,"RATE_LIMIT_ENTRYPOINT").status,"review");
});
test("missing evidence is explicitly unknown, never presumed off",()=>{
 const base=snapshot();
 base.settings.min_tls_version=null;
 base.entrypoints.zone.http_request_firewall_managed="permission_denied";
 const a=auditSnapshot(base);
 assert.equal(pick(a,"TLS_EDGE_MINIMUM").status,"unknown");
 assert.equal(pick(a,"MANAGED_WAF_EXECUTION").status,"unknown");
});
test("observed configured managed entrypoint is not proof rule effectiveness",()=>{
 const base=snapshot();
 base.entrypoints.zone.http_request_firewall_managed="configured";
 const a=auditSnapshot(base);
 const waf=pick(a,"MANAGED_WAF_EXECUTION");
 assert.equal(waf.status,"configured");
 assert.match(waf.qualification,/Cataloged rulesets are not necessarily executed/);
});
test("strict TLS and HTTPS pass only relevant settings checks",()=>{
 const base=snapshot();
 base.settings.min_tls_version="1.3";
 base.settings.ssl="strict";
 const a=auditSnapshot(base);
 assert.equal(pick(a,"TLS_EDGE_MINIMUM").status,"pass");
 assert.equal(pick(a,"ORIGIN_CERTIFICATE_VERIFICATION").status,"pass");
 assert.equal(pick(a,"MANAGED_WAF_EXECUTION").status,"review");
});
test("public Worker bindings must prevent false isolation assurance",()=>{
 const s=snapshot();s.surface.worker_binding_count=1;
 assert.equal(pick(auditSnapshot(s),"PUBLIC_DEMO_ACCESS_BOUNDARY").status,"review");
 s.surface.worker_binding_count=null;
 assert.equal(pick(auditSnapshot(s),"PUBLIC_DEMO_ACCESS_BOUNDARY").status,"unknown");
});
test("a private customer surface lacking Access is flagged; public demo is intentionally different",()=>{
 const base=snapshot();
 base.surface.purpose="private-customer-environment";
 const a=auditSnapshot(base);
 assert.equal(pick(a,"PUBLIC_DEMO_ACCESS_BOUNDARY").status,"action_required");
 base.surface.access_application_present=true;
 assert.equal(pick(auditSnapshot(base),"PUBLIC_DEMO_ACCESS_BOUNDARY").status,"review");
});
test("reject unexpected inputs; never silently swallow secrets, account IDs, IPs, actor records",()=>{
 const raw=snapshot(); raw.token="secret";
 assert.throws(()=>validateSnapshot(raw),/unexpected fields/);
 const another=snapshot();another.settings.api_key="bad";
 assert.throws(()=>auditSnapshot(another),/unexpected fields/);
 const third=snapshot();third.zone_id="sensitive";
 assert.throws(()=>validateSnapshot(third),/unexpected fields/);
});
test("missing and malformed provenance rejected",()=>{
 const s=snapshot();s.origin="trusted-by-blockchain";
 assert.throws(()=>auditSnapshot(s),/origin is declared/);
 const t=snapshot();t.observed_at="yesterday";
 assert.throws(()=>auditSnapshot(t),/UTC ISO/);
 const u=snapshot();u.entrypoints.account.http_ratelimit="maybe";
 assert.throws(()=>auditSnapshot(u),/invalid/);
});
test("JSON key permutation and spaces do not affect evidence hash",()=>{
 const a=snapshot(),b={surface:a.surface,entrypoints:a.entrypoints,settings:a.settings,
   origin:a.origin,observed_at:a.observed_at,zone_alias:a.zone_alias,schema:a.schema};
 assert.equal(evidenceHash(a),evidenceHash(b));
});
test("chronological snapshot diff shows only changed fields and links both digests",()=>{
 const before=snapshot(),after=structuredClone(before);
 after.observed_at="2026-11-16T00:00:00Z";
 after.settings.min_tls_version="1.2";
 after.entrypoints.zone.http_ratelimit="configured";
 const diff=compareSnapshots(before,after);
 assert.equal(diff.change_count,2);
 assert.deepEqual(diff.changes.map(x=>x.field),[
  "settings.min_tls_version","entrypoints.zone.http_ratelimit"
 ]);
 assert.equal(diff.earlier_sha256,evidenceHash(before));
 assert.equal(diff.later_sha256,evidenceHash(after));
 assert.equal(diff.source_origin_attested,false);
});
test("diff rejects wrong scope and backwards time",()=>{
 const a=snapshot(),b=structuredClone(a);
 b.zone_alias="different-zone";
 assert.throws(()=>compareSnapshots(a,b),/different zone aliases/);
 b.zone_alias="fictional-zone";
 assert.throws(()=>compareSnapshots(a,b),/increasing/);
});
