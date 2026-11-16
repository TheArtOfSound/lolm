// Qira Proof public repository preflight. This is a directory inventory, NOT
// a security scan, repository authorization, payment confirmation or approval.
const LIMIT=20;
const MAX_ITEMS=1000;
const timeout=6000;
const noStore={"cache-control":"no-store","content-type":"application/json; charset=utf-8","x-content-type-options":"nosniff","x-robots-tag":"noindex,nofollow","referrer-policy":"no-referrer"};
export function parseRepository(input){
 if(typeof input!=="string"||input.length>240)return null;
 let value=input.trim().replace(/\/+$/,"");
 if(/^https?:\/\//i.test(value)){
  let u;try{u=new URL(value);}catch{return null;}
  if(u.protocol!=="https:"||u.hostname.toLowerCase()!=="github.com"||
    u.username||u.password||u.port||u.search||u.hash)return null;
  value=u.pathname.replace(/^\/+/,"");
 }else{
  value=value.replace(/^github\.com\//i,"");
 }
 const tokens=value.split("/");
 if(tokens.length!==2)return null;
 const [owner,name]=tokens;
 if(!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(owner)||
    !/^[A-Za-z0-9_.-]{1,100}$/.test(name)||
    name==="."||name===".."||name.startsWith(".")||name.endsWith(".git.git"))return null;
 return {owner,name,key:owner.toLowerCase()+"/"+name.toLowerCase()};
}
const output=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:noStore});
async function githubJSON(path,fetcher,signal){
 // The hostname and path prefix are fixed; user input is restricted to two
 // validated GitHub path segments. Redirects are rejected, not followed.
 const result=await fetcher("https://api.github.com"+path,{
  method:"GET",redirect:"error",signal,
  headers:{"Accept":"application/vnd.github+json","User-Agent":"Qira-Proof-Public-Inventory","X-GitHub-Api-Version":"2022-11-28"}
 });
 if(result.status===404)return {kind:"not_found"};
 if(result.status===403||result.status===429)return {kind:"limited"};
 if(!result.ok)return {kind:"unavailable"};
 const length=Number(result.headers.get("content-length"));
 if(Number.isFinite(length)&&length>1048576)return {kind:"unavailable"};
 const raw=await result.text();
 if(raw.length>1048576)return {kind:"unavailable"};
 try{return {kind:"ok",data:JSON.parse(raw)};}catch{return {kind:"unavailable"};}
}
export async function publicRepositoryPreflight(request,env={},fetcher=fetch){
 if(request.method!=="GET"&&request.method!=="HEAD")return output({status:"invalid_method"},405);
 const url=new URL(request.url);
 const parsed=parseRepository(url.searchParams.get("repo"));
 if(!parsed)return output({status:"invalid_repository",message:"Enter a GitHub repository like github.com/owner/repository."},400);
 const cacheKey=new Request("https://qira-proof-preflight.invalid/"+parsed.key);
 const cache=globalThis.caches?.default;
 if(cache){
  try{const hit=await cache.match(cacheKey);if(hit){const text=await hit.text();return new Response(request.method==="HEAD"?null:text,{headers:noStore});}}catch{}
 }
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),timeout);
 try{
  const root="/repos/"+encodeURIComponent(parsed.owner)+"/"+encodeURIComponent(parsed.name);
  const repoResponse=await githubJSON(root,fetcher,controller.signal);
  if(repoResponse.kind!=="ok"){
   const status=repoResponse.kind==="not_found"?"not_public":repoResponse.kind==="limited"?"rate_limited":"unavailable";
   return output({status,message:status==="not_public"?"Not found publicly. Private repositories can still be reviewed with your authorization.":status==="rate_limited"?"GitHub's public lookup limit has been reached. You can continue without this check.":"GitHub's public lookup is temporarily unavailable. You can continue without it."},status==="not_public"?404:503);
  }
  const details=repoResponse.data;
  if(details?.private!==false||details?.full_name?.toLowerCase()!==parsed.key)return output({status:"not_public"},404);
  const contents=await githubJSON(root+"/contents/.github/workflows?ref="+encodeURIComponent(details.default_branch||"HEAD"),fetcher,controller.signal);
  let count=null;
  if(contents.kind==="not_found")count=0;
  else if(contents.kind==="ok"&&Array.isArray(contents.data))count=contents.data.filter(x=>x?.type==="file"&&/\.ya?ml$/i.test(x.name||"")).length;
  else if(contents.kind==="limited"||contents.kind==="unavailable")count=null;
  const status=count===null?"inventory_unavailable":count===0?"no_workflows":count>LIMIT?"outside_standard_scope":"within_scope";
  const responseBody={
   status,repository:parsed.owner+"/"+parsed.name,
   url:"https://github.com/"+parsed.owner+"/"+parsed.name,
   default_branch:typeof details.default_branch==="string"?details.default_branch:null,
   workflow_count:count,
   workflow_count_limit:LIMIT,
   workflow_count_complete:contents.kind==="ok"&&Array.isArray(contents.data)&&contents.data.length<MAX_ITEMS,
   notice:"Public workflow filenames only. No security scan, repository authorization or payment verification occurred."
  };
  const text=JSON.stringify(responseBody);
  if(cache&&contents.kind==="ok"||cache&&contents.kind==="not_found"){
   try{await cache.put(cacheKey,new Response(text,{headers:{"content-type":"application/json","cache-control":"public, max-age=300"}}));}catch{}
  }
  return new Response(request.method==="HEAD"?null:text,{headers:noStore});
 }catch{
  return output({status:"unavailable",message:"The public lookup is temporarily unavailable. You can still request a review."},503);
 }finally{clearTimeout(timer);}
}
