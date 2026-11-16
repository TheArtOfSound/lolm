/* Reproducible single-Worker build; no dependencies and no network. */
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
const base=path.dirname(fileURLToPath(import.meta.url));
export function assemble(){
 const html=fs.readFileSync(path.join(base,"index.html"),"utf8");
 const app=fs.readFileSync(path.join(base,"app.mjs"),"utf8");
 const core=fs.readFileSync(path.join(base,"core.mjs"),"utf8");
 const auth=fs.readFileSync(path.join(base,"github_app.mjs"),"utf8");
 const authBundled=auth.replace(/^import \{SCHEMA,normalizeSnapshot\} from "\.\/core\.mjs";\s*/m,"")
   .replace("export async function handleGitHubApp(", "async function handleGitHubApp(");
 if(authBundled.includes('import {SCHEMA')||authBundled.includes('export async function handleGitHubApp'))
   throw Error("GitHub App source transformation failed");
 const coreBundled=core.replace(/^export /gm,"");
 return [
  "// QIRA Proof static, local-first pilot. No provider credentials on server.",
  "const HTML="+JSON.stringify(html)+";",
  "const APP="+JSON.stringify(app)+";",
  "const CORE="+JSON.stringify(core)+";",
  coreBundled,
  authBundled,
  "const JSON_HEADERS={ 'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff' };",
  "const JS_HEADERS={ 'content-type':'text/javascript; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff' };",
  "const PAGE_HEADERS={ 'content-type':'text/html; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer','x-frame-options':'DENY','x-robots-tag':'noindex, nofollow','permissions-policy':'camera=(),microphone=(),geolocation=()','content-security-policy':\"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'none'; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'\" };",
  "export default {async fetch(request,env){",
  " if(request.method!=='GET'&&request.method!=='HEAD')return new Response('Method Not Allowed',{status:405,headers:{allow:'GET, HEAD'}});",
  " const github=await handleGitHubApp(request,env);",
  " if(github)return github;",
  " const pathname=new URL(request.url).pathname;",
  " if(pathname==='/')return new Response(request.method==='HEAD'?null:HTML,{headers:PAGE_HEADERS});",
  " if(pathname==='/app.mjs')return new Response(request.method==='HEAD'?null:APP,{headers:JS_HEADERS});",
  " if(pathname==='/core.mjs')return new Response(request.method==='HEAD'?null:CORE,{headers:JS_HEADERS});",
  " if(pathname==='/health')return new Response(request.method==='HEAD'?null:JSON.stringify({status:'ready',product:'qira-proof',mode:'local-first',provider_credentials:false,collection_enabled:false,uploads_enabled:false}),{headers:JSON_HEADERS});",
  " return new Response('Not Found',{status:404,headers:{'cache-control':'no-store'}});",
  "}};",
  ""
 ].join("\n");
}
export function build(){
 const dir=path.join(base,"dist");fs.mkdirSync(dir,{recursive:true});
 const file=path.join(dir,"worker.mjs");fs.writeFileSync(file,assemble());
 return file;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 console.log(build());
}
