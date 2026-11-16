/**
 * Qira Event Horizon: Cloudflare configuration evidence gate.
 *
 * Consumes a narrowly scoped, operator-exported READ-ONLY inventory.
 * Never queries Cloudflare directly; never modifies a zone. The input is a
 * self-declared observation, NOT an independently signed cloud attestation.
 *
 * No secret, IP, email, customer, binding value, or zone ID fields allowed.
 * A diagnostic is an evidence-backed control question, NOT a real-world
 * breach likelihood or proven prevention claim.
 */
import {createHash} from "node:crypto";

const PHASES=["http_request_firewall_managed","http_request_firewall_custom","http_ratelimit"];
const ACCEPTABLE_TLS=["1.2","1.3"];
const KEYS=["min_tls_version","ssl","always_use_https","legacy_waf"];
const CHECKS=[
 "TLS_EDGE_MINIMUM","ORIGIN_CERTIFICATE_VERIFICATION","HTTPS_REDIRECT",
 "MANAGED_WAF_EXECUTION","CUSTOM_FIREWALL_ENTRYPOINT","RATE_LIMIT_ENTRYPOINT",
 "PUBLIC_DEMO_ACCESS_BOUNDARY"
];
const ALLOWED_STATES=["configured","no_entrypoint","unknown","permission_denied"];
function isRecord(v){return v!==null&&typeof v==="object"&&!Array.isArray(v);}
function requireKeys(v,expected,label){
 if(!isRecord(v)||Object.keys(v).some(k=>!expected.includes(k))||expected.some(k=>!(k in v)))
   throw new Error(label+" has missing or unexpected fields");
}
function evidenceHash(snapshot){
 // Canonical recursive sort of keys for a stable digest regardless of
 // input formatting. This is integrity only, not origin authentication.
 function sort(v){if(Array.isArray(v))return v.map(sort);if(isRecord(v))
   return Object.fromEntries(Object.keys(v).sort().map(k=>[k,sort(v[k])]));return v;}
 return createHash("sha256").update(JSON.stringify(sort(snapshot))).digest("hex");
}
function validateSnapshot(s){
 requireKeys(s,["schema","zone_alias","observed_at","origin","settings","entrypoints","surface"],"snapshot");
 if(s.schema!=="qira-edge-inventory/v1")throw new Error("unsupported snapshot schema");
 if(typeof s.zone_alias!=="string"||!/^[-a-z0-9]{3,48}$/.test(s.zone_alias))
   throw new Error("zone_alias must be non-identifying slug");
 if(typeof s.observed_at!=="string"||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z$/.test(s.observed_at)
   ||!Number.isFinite(Date.parse(s.observed_at)))throw new Error("observation time must be UTC ISO-8601");
 if(s.origin!=="operator-exported-cloudflare-readonly")
   throw new Error("origin is declared, not automatically attested");
 requireKeys(s.settings,KEYS,"settings");
 if(!["1.0","1.1","1.2","1.3",null].includes(s.settings.min_tls_version))throw new Error("invalid minimum TLS");
 if(!["off","flexible","full","strict",null].includes(s.settings.ssl))throw new Error("invalid SSL mode");
 for(const key of ["always_use_https","legacy_waf"])
   if(!["on","off",null].includes(s.settings[key]))throw new Error("invalid "+key);
 requireKeys(s.entrypoints,["account","zone"],"entrypoints");
 for(const scope of ["account","zone"]){
   requireKeys(s.entrypoints[scope],PHASES,scope+" entrypoints");
   for(const phase of PHASES)if(!ALLOWED_STATES.includes(s.entrypoints[scope][phase]))
      throw new Error("invalid "+scope+" "+phase+" state");
 }
 requireKeys(s.surface,["purpose","access_application_present","worker_binding_count"],"surface");
 if(!["public-synthetic-demo","private-customer-environment","unknown"].includes(s.surface.purpose))
   throw new Error("unknown surface purpose");
 if(typeof s.surface.access_application_present!=="boolean"&&s.surface.access_application_present!==null)
   throw new Error("invalid Access observation");
 if(!Number.isSafeInteger(s.surface.worker_binding_count)&&s.surface.worker_binding_count!==null)
   throw new Error("invalid binding count");
 if(s.surface.worker_binding_count!==null&&(s.surface.worker_binding_count<0||s.surface.worker_binding_count>100))
   throw new Error("binding count out of scope");
 return s;
}
function finding(id,status,observed,evidence,advice,qualification){
 return {id,status,observed,evidence,advice,qualification};
}
function auditSnapshot(data){
 const s=validateSnapshot(data),cfg=s.settings;
 const f=[];
 const tls=cfg.min_tls_version;
 f.push(finding(CHECKS[0],tls===null?"unknown":ACCEPTABLE_TLS.includes(tls)?"pass":"review",
   tls,"settings.min_tls_version",
   "Review all clients before increasing minimum edge TLS to 1.2 or higher; this is a zone-wide compatibility decision.",
   "The setting is observed; client impact and actual exploitability are not measured."));
 const ssl=cfg.ssl;
 f.push(finding(CHECKS[1],ssl===null?"unknown":ssl==="strict"?"pass":"review",
   ssl,"settings.ssl",
   "Validate every origin's certificate/hostname chain and proxy configuration before migrating to Full (strict).",
   "Full mode provides origin encryption but does not verify the origin certificate as strict mode does."));
 const https=cfg.always_use_https;
 f.push(finding(CHECKS[2],https===null?"unknown":https==="on"?"pass":"review",
   https,"settings.always_use_https",
   "Confirm HTTPS redirect at the edge and avoid blanket zone changes without endpoint compatibility checks.",
   "An enabled setting does not verify every origin or route."));
 for(const [id,phase,label] of [
   [CHECKS[3],"http_request_firewall_managed","managed WAF"],
   [CHECKS[4],"http_request_firewall_custom","custom firewall"],
   [CHECKS[5],"http_ratelimit","HTTP rate limiting"]]){
   const states={account:s.entrypoints.account[phase],zone:s.entrypoints.zone[phase]};
   const values=Object.values(states);
   const status=values.includes("configured")?"configured":
     values.every(v=>v==="no_entrypoint")?"review":"unknown";
   f.push(finding(id,status,states,"entrypoints.account."+phase+"; entrypoints.zone."+phase,
     status==="review"?"Review whether a scoped, tested "+label+" entrypoint is appropriate; avoid unexpected false positives.":"Confirm effective application of any configured "+label+" and its actual traffic scope.",
     "An absent entrypoint does not demonstrate absence of all Cloudflare default protections. Cataloged rulesets are not necessarily executed."));
 }
 let exposureStatus="unknown",meaning="Insufficient evidence to classify purpose and exposure.";
 if(s.surface.purpose==="public-synthetic-demo"){
   if(s.surface.worker_binding_count===null){
     exposureStatus="unknown";
     meaning="Binding count was not observed; do not certify public isolation without inspecting effective bindings and code.";
   }else if(s.surface.worker_binding_count>0){
     exposureStatus="review";
     meaning="The public synthetic research Worker has bindings; inspect scope and ensure it cannot expose credentials or customer data.";
   }else{
     exposureStatus="intentional_public";
     meaning="Public access can be appropriate for synthetic-only read-only demonstrations; customer evidence must not enter this environment.";
   }
 }else if(s.surface.purpose==="private-customer-environment"){
   exposureStatus=s.surface.access_application_present===true?"review":"action_required";
   meaning="Presence of an Access app alone does not prove enforcement or tenant isolation. Independently test permissions and authentication.";
 }
 f.push(finding(CHECKS[6],exposureStatus,
  {purpose:s.surface.purpose,access_application_present:s.surface.access_application_present,
   worker_binding_count:s.surface.worker_binding_count},"surface",
  "Maintain separate private authenticated services for any real evidence; verify access independently.",
  meaning));
 const counts=Object.fromEntries([...new Set(f.map(x=>x.status))].sort().map(status=>[status,f.filter(x=>x.status===status).length]));
 return {schema:"qira-edge-posture-audit/v1",zone_alias:s.zone_alias,observed_at:s.observed_at,
   snapshot_sha256:evidenceHash(s),source_origin_attested:false,read_only:true,protection_claims_validated:false,
   findings:f,counts,disclaimer:"Configuration observations and static checks only; not a penetration test or proof of incident prevention."};
}
function compareSnapshots(previous,current){
 const left=validateSnapshot(previous),right=validateSnapshot(current);
 if(left.zone_alias!==right.zone_alias)throw new Error("cannot compare different zone aliases");
 if(Date.parse(right.observed_at)<=Date.parse(left.observed_at))throw new Error("snapshots must be increasing in observation time");
 const changes=[];
 function recurse(a,b,path){
   if(isRecord(a)&&isRecord(b)){for(const k of Object.keys(a).sort())recurse(a[k],b[k],path?path+"."+k:k);return;}
   if(JSON.stringify(a)!==JSON.stringify(b))changes.push({field:path,before:a,after:b});
 }
 recurse(left.settings,right.settings,"settings");
 recurse(left.entrypoints,right.entrypoints,"entrypoints");
 recurse(left.surface,right.surface,"surface");
 return {schema:"qira-edge-posture-diff/v1",zone_alias:left.zone_alias,
   earlier_sha256:evidenceHash(left),later_sha256:evidenceHash(right),changes,
   change_count:changes.length,source_origin_attested:false,
   note:"Observed configuration changes do not establish a causal effect on threats or business outcomes."};
}
export {PHASES,validateSnapshot,auditSnapshot,compareSnapshots,evidenceHash};
