/*
 * QIRA Proof / opt-in GitHub App user-to-server read-only connector.
 *
 * No provider credentials in HTML, cookies contain only AES-GCM ciphertext,
 * and no provider token or source code is persisted in Worker storage.
 *
 * Important: this is a short-lived PILOT session, not multi-tenant SaaS identity.
 * The GitHub App must be registered independently with Contents:read and
 * Metadata:read, PKCE enabled, expiring user tokens, and exact callback URL.
 */
import {SCHEMA,normalizeSnapshot} from "./core.mjs";

const COOKIE_PENDING="__Host-qira_git_state";
const COOKIE_SESSION="__Host-qira_git_session";
const STATE_TTL_MS=10*60*1000;
const SESSION_TTL_MS=15*60*1000;
const MAX_RESPONSE_BYTES=500_000;
const MAX_WORKFLOW_BYTES=128_000;
const RESP_HEADERS={
 "cache-control":"private, no-store, max-age=0",
 "x-content-type-options":"nosniff",
 "referrer-policy":"no-referrer",
 "x-frame-options":"DENY",
 "content-security-policy":"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
 "vary":"Cookie"
};
const json=(value,status=200,extra={})=>new Response(JSON.stringify(value),{status,headers:{...RESP_HEADERS,"content-type":"application/json; charset=utf-8",...extra}});
const fail=(reason,status)=>json({error:reason},status);
const OAUTH_REASONS = new Set(["authorization_denied","state_missing","state_expired","state_mismatch","code_missing","client_credentials","callback_mismatch","token_expiration_disabled","token_invalid","provider_unavailable","session_unavailable",
 "authorization_code_rejected","email_unverified","app_suspended","exchange_transport","exchange_http_4xx","exchange_http_5xx","provider_rejected"]);
class OAuthFailure extends Error {
 constructor(reason){super("OAuth failed");this.reason=OAUTH_REASONS.has(reason)?reason:"provider_unavailable";}
}
const oauthError=reason=>new OAuthFailure(reason);
const oauthFailureRedirect=(env,reason)=>responseRedirect(publicOrigin(env)+"/?github=failed&reason="+
 encodeURIComponent(OAUTH_REASONS.has(reason)?reason:"provider_unavailable"),[clearCookie(COOKIE_PENDING)]);

const urlSafe=(s)=>typeof s==="string"&&/^[a-zA-Z0-9_-]+$/.test(s);
const repoSafe=(s)=>typeof s==="string"&&/^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/.test(s)&&!s.includes("..");
const workflowSafe=(s)=>typeof s==="string"&&/^\.github\/workflows\/[A-Za-z0-9_.-]{1,125}\.ya?ml$/.test(s)&&!s.includes("..");
const b64url=(a)=>btoa(String.fromCharCode(...a)).replaceAll("+","-").replaceAll("/","_").replace(/=+$/,"");
const unb64=(s)=>{
 if(typeof s!=="string"||s.length>4096||!urlSafe(s))throw Error("invalid ciphertext encoding");
 const raw=atob(s.replaceAll("-","+").replaceAll("_","/"));return Uint8Array.from(raw,c=>c.charCodeAt(0));
};
const random=(n)=>b64url(crypto.getRandomValues(new Uint8Array(n)));
const now=()=>Date.now();
function same(a,b){
 if(typeof a!=="string"||typeof b!=="string")return false;
 const len=Math.max(a.length,b.length);let different=a.length^b.length;
 for(let i=0;i<len;i++)different|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);
 return different===0;
}
function publicOrigin(env){
 const raw=env.QIRA_PUBLIC_ORIGIN;
 if(typeof raw!=="string")return null;
 try{
  const u=new URL(raw);
  if(u.protocol!=="https:"||u.username||u.password||u.pathname!=="/"||u.search||u.hash)return null;
  return u.origin;
 }catch{return null}
}
function configured(env){
 return !!(publicOrigin(env)&&typeof env.GITHUB_APP_CLIENT_ID==="string"&&/^[A-Za-z0-9_.-]{8,180}$/.test(env.GITHUB_APP_CLIENT_ID)&&
 typeof env.GITHUB_APP_CLIENT_SECRET==="string"&&env.GITHUB_APP_CLIENT_SECRET.length>=12&&
 typeof env.QIRA_SESSION_KEY==="string"&&/^[A-Za-z0-9_-]{43}$/.test(env.QIRA_SESSION_KEY));
}
async function key(env){
 if(!configured(env))throw Error("connector not configured");
 const raw=unb64(env.QIRA_SESSION_KEY);
 if(raw.length!==32)throw Error("invalid session encryption key");
 return crypto.subtle.importKey("raw",raw,{name:"AES-GCM"},false,["encrypt","decrypt"]);
}
async function seal(env,purpose,document){
 const iv=crypto.getRandomValues(new Uint8Array(12));
 const aad=new TextEncoder().encode("QIRA|"+purpose+"|"+publicOrigin(env));
 const text=new TextEncoder().encode(JSON.stringify(document));
 const body=new Uint8Array(await crypto.subtle.encrypt({name:"AES-GCM",iv,additionalData:aad},await key(env),text));
 return b64url(iv)+"."+b64url(body);
}
async function openSealed(env,purpose,token){
 if(typeof token!=="string"||token.length>3500||!/^[-\w]+\.[-\w]+$/.test(token))return null;
 try{
  const [ivText,bodyText]=token.split(".");
  const iv=unb64(ivText),body=unb64(bodyText);
  if(iv.length!==12||body.length>2500)return null;
  const aad=new TextEncoder().encode("QIRA|"+purpose+"|"+publicOrigin(env));
  const plaintext=await crypto.subtle.decrypt({name:"AES-GCM",iv,additionalData:aad},await key(env),body);
  const value=JSON.parse(new TextDecoder().decode(plaintext));
  return value&&typeof value==="object"&&!Array.isArray(value)?value:null;
 }catch{return null}
}
function cookies(request){
 const raw=request.headers.get("cookie")||"";
 const result={};
 for(const segment of raw.split(";")){
  const i=segment.indexOf("=");
  if(i>0)result[segment.slice(0,i).trim()]=segment.slice(i+1).trim();
 }
 return result;
}
const cookie=(name,value,age)=>name+"="+value+"; Path=/; Max-Age="+age+"; HttpOnly; Secure; SameSite=Lax";
const clearCookie=(name)=>cookie(name,"",0);
async function sessionFor(request,env,clock=now){
 const c=cookies(request);
 const record=await openSealed(env,"session",c[COOKIE_SESSION]);
 if(!record||record.v!==1||typeof record.token!=="string"||record.token.length<20||
 typeof record.csrf!=="string"||!urlSafe(record.csrf)||!Number.isSafeInteger(record.exp)||
 record.exp<=clock()||record.exp>clock()+SESSION_TTL_MS)return null;
 return record;
}
function checkHost(request,env){
 return publicOrigin(env)!==null&&new URL(request.url).origin===publicOrigin(env);
}
// Distinguish an absent or hidden workflow folder (404) from server failures
// without exposing GitHub response bodies or tokens.
class GitHubReadError extends Error {
 constructor(status){super("GitHub metadata unavailable");this.status=status;}
}
async function githubGet(path,token,fetcher=fetch){
 if(!path.startsWith("/")||path.startsWith("//")||path.includes("..")||path.includes("\\"))
  throw Error("GitHub request path rejected");
 const u="https://api.github.com"+path;
 const response=await fetcher(u,{method:"GET",redirect:"manual",
   headers:{"authorization":"Bearer "+token,"accept":"application/vnd.github+json",
      "x-github-api-version":"2026-03-10","user-agent":"qira-proof-readonly-pilot"}});
 // Cloudflare Workers does not support redirect:'error'. Explicit manual mode
 // and a no-redirect policy preserve the original security requirement.
 if(response.status>=300&&response.status<400||response.type==="opaqueredirect")
  throw Error("GitHub API redirect rejected");
 if(!response.ok)throw new GitHubReadError(response.status);
 const text=await response.text();
 if(text.length>MAX_RESPONSE_BYTES)throw Error("GitHub metadata exceeded budget");
 return JSON.parse(text);
}
async function installations(token,fetcher){
 const payload=await githubGet("/user/installations?per_page=50",token,fetcher);
 if(!payload||!Array.isArray(payload.installations))throw Error("malformed installations response");
 const items=payload.installations.slice(0,50)
 .filter(x=>Number.isSafeInteger(x.id)&&x.id>0&&typeof x.account?.login==="string")
 .map(x=>({id:x.id,account:x.account.login,selection:x.repository_selection==="selected"?"selected":"all"}));
 return {items,truncated:payload.total_count>payload.installations.length};
}
async function accessibleRepos(token,installationId,fetcher){
 if(!Number.isSafeInteger(installationId)||installationId<=0)return null;
 const known=await installations(token,fetcher);
 if(!known.items.some(x=>x.id===installationId))return null;
 const payload=await githubGet("/user/installations/"+installationId+"/repositories?per_page=100",token,fetcher);
 if(!payload||!Array.isArray(payload.repositories))throw Error("malformed repositories response");
 const repos=payload.repositories.filter(x=>repoSafe(x.full_name)&&typeof x.default_branch==="string"&&
 x.default_branch.length<=128&&/^[A-Za-z0-9_.\/-]+$/.test(x.default_branch)&&!x.default_branch.includes(".."))
 .map(x=>({name:x.full_name,branch:x.default_branch}));
 return {repos,truncated:payload.total_count>payload.repositories.length};
}
async function listWorkflows(token,installationId,repo,fetcher){
 if(!repoSafe(repo))throw Error("invalid repository");
 const allowed=await accessibleRepos(token,installationId,fetcher);
 if(!allowed)throw Error("installation not authorized");
 const selected=allowed.repos.find(x=>x.name===repo);
 if(!selected)throw Error("repository not within verified authorized installation");
 const [owner,name]=repo.split("/");
 const uri="/repos/"+encodeURIComponent(owner)+"/"+encodeURIComponent(name)+
   "/contents/.github/workflows?ref="+encodeURIComponent(selected.branch);
 let raw;
 try{raw=await githubGet(uri,token,fetcher)}
 catch(error){
  // GitHub returns 404 when .github/workflows is absent, but may also hide
  // an inaccessible folder. Never misrepresent this as a confirmed absence.
  if(error instanceof GitHubReadError&&error.status===404)
   return {repo,branch:selected.branch,workflows:[],truncated:false,
    availability:"directory_not_found_or_inaccessible"};
  throw error;
 }
 if(!Array.isArray(raw))throw Error("workflow metadata unavailable");
 const workflows=raw.filter(x=>x.type==="file"&&workflowSafe(x.path)).slice(0,100)
   .map(x=>({path:x.path}));
 return {repo,branch:selected.branch,workflows,truncated:raw.length>100,
  availability:workflows.length?"available":"no_supported_workflows"};
}
function sourceUrl(repo,branch,workflow){
 return "https://github.com/"+repo+"/blob/"+encodeURIComponent(branch)+"/"+workflow;
}
const BULK_WORKFLOW_LIMIT=20;
const BULK_BATCH_SIZE=4;
// Boolean facts are limited to syntactic evidence visible in each selected file.
// Policy outcomes, provider access, and the execution context are NOT inferred.
function workflowFacts(text,repo,workflow,commit,timestamp,asset){
 const lines=text.split(/\r?\n/).filter(x=>!x.trimStart().startsWith("#"));
 const runtimeScan=lines.some(x=>/(^|[^A-Za-z0-9_-])ssh-keyscan(?:[ \t]|$)/.test(x));
 const actionRef=/^\s*(?:-\s*)?uses:\s*['"]?([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_./-]+)?)@([A-Za-z0-9_.-]{1,128})['"]?(?:\s*(?:#.*)?)?$/;
 const unpinned=lines.some(line=>{
  const m=actionRef.exec(line);
  return !!m&&!/^[a-fA-F0-9]{40}$/.test(m[2]);
 });
 const url=sourceUrl(repo,commit,workflow);
 const facts=[
  {provider:"github",asset,signal:"runtime_ssh_keyscan",value:runtimeScan,source_url:url,observed_at:timestamp},
  {provider:"github",asset,signal:"workflow_unpinned_actions",value:unpinned,source_url:url,observed_at:timestamp}
 ];
 if(runtimeScan)facts.push({provider:"github",asset,signal:"ssh_host_key_pinned",value:"unknown",source_url:url,observed_at:timestamp});
 return facts;
}
async function resolveWorkflowCommit(apiRepo,branch,token,fetcher){
 const revision=await githubGet(apiRepo+"/commits/"+encodeURIComponent(branch),token,fetcher);
 if(!revision||typeof revision.sha!=="string"||!/^[a-fA-F0-9]{40}$/.test(revision.sha))
  throw Error("GitHub workflow revision could not be verified");
 return revision.sha.toLowerCase();
}
async function readWorkflowFacts(token,repo,workflow,commit,asset,timestamp,fetcher){
 const [owner,name]=repo.split("/");
 const apiRepo="/repos/"+encodeURIComponent(owner)+"/"+encodeURIComponent(name);
 const path=apiRepo+"/contents/"+workflow.split("/").map(encodeURIComponent).join("/")+"?ref="+commit;
 const data=await githubGet(path,token,fetcher);
 if(data?.encoding!=="base64"||typeof data.content!=="string"||data.content.length>MAX_WORKFLOW_BYTES*2)
  throw Error("workflow not returned as bounded base64");
 const bytes=atob(data.content.replace(/\s/g,""));
 if(bytes.length>MAX_WORKFLOW_BYTES)throw Error("workflow size budget exceeded");
 const text=new TextDecoder("utf-8",{fatal:true}).decode(Uint8Array.from(bytes,c=>c.charCodeAt(0)));
 return workflowFacts(text,repo,workflow,commit,timestamp,asset);
}
function visibilityFact(repo,timestamp){
 return {provider:"github",asset:repo,signal:"repo_branch_protection_verifiable",value:"unknown",
  source_url:"https://github.com/"+repo+"/settings/branches",observed_at:timestamp};
}
async function assess(token,installationId,repo,workflow,fetcher,clock=now){
 if(!repoSafe(repo)||!workflowSafe(workflow))throw Error("repository or workflow selector invalid");
 const allowed=await accessibleRepos(token,installationId,fetcher);
 if(!allowed)throw Error("installation not authorized");
 const selected=allowed.repos.find(r=>r.name===repo);
 if(!selected)throw Error("repository not within verified authorized installation page");
 const [owner,name]=repo.split("/");
 const apiRepo="/repos/"+encodeURIComponent(owner)+"/"+encodeURIComponent(name);
 const commit=await resolveWorkflowCommit(apiRepo,selected.branch,token,fetcher);
 const timestamp=new Date(clock()).toISOString();
 const facts=await readWorkflowFacts(token,repo,workflow,commit,repo,timestamp,fetcher);
 facts.push(visibilityFact(repo,timestamp));
 return normalizeSnapshot({schema:SCHEMA,captured_at:timestamp,facts});
}
async function assessRepository(token,installationId,repo,fetcher,clock=now){
 if(!repoSafe(repo))throw Error("repository selector invalid");
 const listed=await listWorkflows(token,installationId,repo,fetcher);
 if(!listed.workflows.length)
  throw Error("No accessible GitHub Actions workflow to review");
 const all=listed.workflows.map(x=>x.path);
 const selected=all.slice(0,BULK_WORKFLOW_LIMIT);
 const [owner,name]=repo.split("/");
 const apiRepo="/repos/"+encodeURIComponent(owner)+"/"+encodeURIComponent(name);
 const commit=await resolveWorkflowCommit(apiRepo,listed.branch,token,fetcher);
 const timestamp=new Date(clock()).toISOString();
 const facts=[visibilityFact(repo,timestamp)];
 let assessed=0,skipped=0;
 for(let offset=0;offset<selected.length;offset+=BULK_BATCH_SIZE){
  const slice=selected.slice(offset,offset+BULK_BATCH_SIZE);
  const responses=await Promise.allSettled(slice.map(async workflow=>{
   const asset=repo+":"+workflow;
   // Strictly reject long assets rather than truncating names and conflating scopes.
   if(asset.length>180)throw Error("Workflow asset exceeds bound");
   return readWorkflowFacts(token,repo,workflow,commit,asset,timestamp,fetcher);
  }));
  responses.forEach(result=>{
   if(result.status==="fulfilled"){facts.push(...result.value);assessed++}
   else skipped++;
  });
 }
 if(!assessed)throw Error("No selected workflow could be inspected");
 const snapshot=normalizeSnapshot({schema:SCHEMA,captured_at:timestamp,facts});
 return {snapshot,coverage:{mode:"bounded-repository-workflows",repository:repo,
  discovered:all.length,selected:selected.length,assessed,skipped,
  limit:BULK_WORKFLOW_LIMIT,complete:!listed.truncated&&selected.length===all.length&&skipped===0,
  truncated:listed.truncated||all.length>BULK_WORKFLOW_LIMIT,commit}};
}
function responseRedirect(to,setCookies=[]){
 const h=new Headers(RESP_HEADERS);
 h.set("location",to);
 for(const v of setCookies)h.append("set-cookie",v);
 return new Response(null,{status:303,headers:h});
}
async function pkceChallenge(verifier){
 const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(verifier)));
 return b64url(digest);
}
async function exchangeToken(env,code,verifier,fetcher){
 const body=new URLSearchParams({
  client_id:env.GITHUB_APP_CLIENT_ID,client_secret:env.GITHUB_APP_CLIENT_SECRET,
  code,redirect_uri:publicOrigin(env)+"/oauth/github/callback",code_verifier:verifier
 });
 let response;
 try {response=await fetcher("https://github.com/login/oauth/access_token",{
  method:"POST",redirect:"manual",headers:{"accept":"application/json",
    "content-type":"application/x-www-form-urlencoded","user-agent":"qira-proof-readonly-pilot"},
  body:body.toString()
 });}catch{throw oauthError("exchange_transport");}
 // Never follow the OAuth POST to an unexpected host, even if GitHub issues a
 // redirect. Do not read or echo Location headers or token response bodies.
 if(response.status>=300&&response.status<400||response.type==="opaqueredirect")
  throw oauthError("exchange_http_4xx");
 let parsed;
 try {
  const raw=await response.text();
  if(raw.length>5000)throw Error("Over budget");
  parsed=JSON.parse(raw);
 }catch{
  if(!response.ok)throw oauthError(response.status>=500?"exchange_http_5xx":"exchange_http_4xx");
  throw oauthError("token_invalid");
 }
 if(parsed&&typeof parsed==="object"&&typeof parsed.error==="string"){
  const errors={
   incorrect_client_credentials:"client_credentials",
   redirect_uri_mismatch:"callback_mismatch",
   bad_verification_code:"authorization_code_rejected",
   unverified_user_email:"email_unverified",
   application_suspended:"app_suspended"
  };
  // GitHub's error_description, error_uri, and any raw response contents
  // must never reach the redirect URL, logs, client or exported reports.
  throw oauthError(Object.hasOwn(errors,parsed.error)?errors[parsed.error]:"provider_rejected");
 }
 if(!response.ok)throw oauthError(response.status>=500?"exchange_http_5xx":"exchange_http_4xx");
 if(!parsed||typeof parsed!=="object"||Array.isArray(parsed))throw oauthError("token_invalid");
 if(parsed.expires_in===undefined)throw oauthError("token_expiration_disabled");
 if(typeof parsed.access_token!=="string"||parsed.access_token.length<20||
 typeof parsed.token_type!=="string"||parsed.token_type.toLowerCase()!=="bearer"||
 !Number.isInteger(parsed.expires_in)||parsed.expires_in<120||parsed.expires_in>28800)
  throw oauthError("token_invalid");
 return {token:parsed.access_token,ttl:Math.min(SESSION_TTL_MS,parsed.expires_in*1000)};
}
function cspGet(request){return ["GET","HEAD"].includes(request.method)}
export async function handleGitHubApp(request,env={}, {fetcher=fetch,clock=now}={}){
 const url=new URL(request.url),path=url.pathname;
 if(path!=="/api/github/status"&&path!=="/connect/github"&&
    path!=="/oauth/github/callback"&&path!=="/api/github/disconnect"&&
    !path.startsWith("/api/github/"))return null;
 if(path==="/api/github/status"){
  const setup=configured(env);
  const sess=setup?await sessionFor(request,env,clock):null;
  let slug=typeof env.GITHUB_APP_SLUG==="string"&&/^[A-Za-z0-9-]{1,100}$/.test(env.GITHUB_APP_SLUG)?env.GITHUB_APP_SLUG:null;
  return json({configured:setup,connected:!!sess,expires_at:sess?new Date(sess.exp).toISOString():null,
    csrf:sess?sess.csrf:null,install_url:setup&&slug?"https://github.com/apps/"+slug+"/installations/new":null});
 }
 if(!configured(env)||!checkHost(request,env))return fail("GitHub App connection is not configured for this origin",503);
 if(path==="/connect/github"&&cspGet(request)){
  const nonce=random(24),verifier=random(48),challenge=await pkceChallenge(verifier);
  const pending=await seal(env,"pending",{v:1,nonce,verifier,exp:clock()+STATE_TTL_MS});
  const target=new URL("https://github.com/login/oauth/authorize");
  target.searchParams.set("client_id",env.GITHUB_APP_CLIENT_ID);
  target.searchParams.set("redirect_uri",publicOrigin(env)+"/oauth/github/callback");
  target.searchParams.set("state",nonce);
  target.searchParams.set("code_challenge",challenge);
  target.searchParams.set("code_challenge_method","S256");
  return responseRedirect(target.toString(),[cookie(COOKIE_PENDING,pending,600)]);
 }
 if(path==="/oauth/github/callback"&&cspGet(request)){
  const state=url.searchParams.get("state"),code=url.searchParams.get("code");
  const pending=await openSealed(env,"pending",cookies(request)[COOKIE_PENDING]);
  if(url.searchParams.has("error"))return oauthFailureRedirect(env,"authorization_denied");
  if(!pending||pending.v!==1)return oauthFailureRedirect(env,"state_missing");
  if(pending.exp<=clock()||pending.exp>clock()+STATE_TTL_MS)
   return oauthFailureRedirect(env,"state_expired");
  if(!same(state,pending.nonce))return oauthFailureRedirect(env,"state_mismatch");
  if(!urlSafe(code)||code.length>256)return oauthFailureRedirect(env,"code_missing");
  let token;
  try{token=await exchangeToken(env,code,pending.verifier,fetcher)}
  catch(error){
   const reason=error instanceof OAuthFailure?error.reason:"provider_unavailable";
   // Deliberately log ONLY the fixed reason code. Never log request URLs,
   // authorization codes, client credentials, provider bodies, or cookie data.
   console.warn("qira.github.oauth_exchange_failure",reason);
   return oauthFailureRedirect(env,reason);
  }
  try{
   const session=await seal(env,"session",{v:1,token:token.token,exp:clock()+token.ttl,csrf:random(24)});
   if(session.length>3600)throw Error("session over cookie bound");
   return responseRedirect(publicOrigin(env)+"/?github=connected",
      [clearCookie(COOKIE_PENDING),cookie(COOKIE_SESSION,session,Math.floor(token.ttl/1000))]);
  }catch{return oauthFailureRedirect(env,"session_unavailable")}
 }
 if(path==="/api/github/disconnect"){
  if(request.method!=="POST")return fail("Method not allowed",405);
  if(request.headers.get("origin")!==publicOrigin(env))return fail("Invalid request origin",403);
  const session=await sessionFor(request,env,clock);
  if(!session||!same(request.headers.get("x-qira-csrf"),session.csrf))return fail("Invalid session or CSRF token",403);
  const res=json({disconnected:true,server_side_token_revoked:false});
  res.headers.append("set-cookie",clearCookie(COOKIE_SESSION));
  return res;
 }
 if(path.startsWith("/api/github/")){
  const session=await sessionFor(request,env,clock);
  if(!session)return fail("Connect your GitHub App first",401);
  if(path==="/api/github/installations"){
   if(request.method!=="GET")return fail("Method not allowed",405);
   try{return json(await installations(session.token,fetcher))}
   catch{return fail("GitHub installation list unavailable",502)}
  }
  if(!["/api/github/repos","/api/github/workflows","/api/github/assessment"].includes(path))
   return fail("Not found",404);
  // Selection data is POSTed so private repository paths do not enter URL logs.
  // These are READ-only operations to GitHub, despite the local HTTP method.
  if(request.method!=="POST")return fail("Method not allowed",405);
  if(request.headers.get("origin")!==publicOrigin(env)||
    !same(request.headers.get("x-qira-csrf"),session.csrf))return fail("Invalid request origin or CSRF",403);
  if(!(request.headers.get("content-type")||"").toLowerCase().startsWith("application/json"))
   return fail("JSON required",415);
  if(Number(request.headers.get("content-length")||"0")>2048)return fail("Request size exceeded",413);
  let fields;
  try{
   const body=await request.text();
   if(body.length>2048)throw Error("Too long");
   fields=JSON.parse(body);
  }catch{return fail("Invalid request JSON",400)}
  const expected=path==="/api/github/repos"?["installation_id"]:
    path==="/api/github/workflows"?["installation_id","repo"]:
    ["installation_id","repo","workflow"];
  if(!fields||Array.isArray(fields)||typeof fields!=="object"||
    Object.keys(fields).length!==expected.length||
    Object.keys(fields).some(k=>!expected.includes(k))||
    !Number.isSafeInteger(fields.installation_id)||fields.installation_id<=0)
   return fail("Unexpected request selection",400);
  try{
   if(path==="/api/github/repos"){
    const data=await accessibleRepos(session.token,fields.installation_id,fetcher);
    return data?json(data):fail("Installation not authorized",403);
   }
   if(path==="/api/github/workflows")
    return json(await listWorkflows(session.token,fields.installation_id,fields.repo,fetcher));
   if(path==="/api/github/assessment"&&fields.workflow==="__all__"){
    const result=await assessRepository(session.token,fields.installation_id,fields.repo,fetcher,clock);
    return json({...result,note:"Bounded read-only repository workflow review; browser analysis required"});
   }
   const data=await assess(session.token,fields.installation_id,
      fields.repo,fields.workflow,fetcher,clock);
   return json({snapshot:data,note:"Authorized read-only GitHub metadata; browser analysis required"});
  }catch{return fail("GitHub read-only inspection unavailable or authorization is insufficient",502)}
 }
 return null;
}
