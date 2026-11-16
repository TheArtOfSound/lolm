import test from "node:test";
import assert from "node:assert/strict";
import worker from "../commercial/landing.mjs";
import {GUIDES,renderGuide} from "../commercial/guides.mjs";
import {ORIGIN,INDEX_PATHS,SEO_PAGES,canonicalFor,sitemapXml,robotsTxt,NON_INDEXABLE} from "../commercial/seo.mjs";
const visit=(path,options={})=>worker.fetch(new Request(ORIGIN+path,options),{QIRA_PROOF_CHECKOUT_URL:"https://buy.stripe.com/9B63cvexo0ts3OBfyv7kc07"});
const allPaths=[...INDEX_PATHS];

test("9 genuinely distinct public search landing pages respond 200 with SEO metadata",async()=>{
 assert.equal(new Set(allPaths).size,9);
 assert.ok(allPaths.includes("/case-study"));
 assert.ok(allPaths.includes("/methodology"));
 assert.ok(allPaths.includes("/guides"));
 const titles=[],descriptions=[];
 for(const path of allPaths){
  const result=await visit(path);
  assert.equal(result.status,200,path);
  assert.match(result.headers.get("content-type"),/text\/html/);
  const html=await result.text();
  const title=html.match(/<title>([^<]+)<\/title>/)?.[1];
  const description=html.match(/<meta name="description" content="([^"]+)">/)?.[1];
  assert.ok(title&&title.length>=35&&title.length<=85,path+" title: "+title);
  assert.ok(description&&description.length>=85&&description.length<=190,path+" description: "+description);
  titles.push(title);descriptions.push(description);
  assert.equal((html.match(/rel="canonical"/g)||[]).length,1,path+" one canonical");
  assert.ok(html.includes('rel="canonical" href="'+canonicalFor(path)+'"'),path+" canonical URL");
  assert.match(html,/<meta name="robots" content="index,follow,max-image-preview:large">/);
  assert.ok(html.includes('property="og:url" content="'+canonicalFor(path)+'"'),path+" OG URL");
  assert.match(html,/<meta name="twitter:card" content="summary">/);
  assert.match(html,/<meta property="og:title" content="[^"]+">/);
  assert.match(html,/<script type="application\/ld\+json">/);
  assert.match(html,/<h1(?:\s[^>]*)?>/);
  assert.doesNotMatch(html,/<meta name="robots" content="noindex/);
 }
 assert.equal(new Set(titles).size,allPaths.length);
 assert.equal(new Set(descriptions).size,allPaths.length);
});

test("schema.org JSON-LD is parseable, accurately identifies service not fake testimonials",async()=>{
 const homepage=await (await visit("/")).text();
 const schema=JSON.parse(homepage.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)?.[1]);
 assert.equal(schema["@context"],"https://schema.org");
 const service=schema["@graph"].find(x=>x["@type"]==="Service");
 assert.equal(service.name,"Qira Proof Founding Workflow Review");
 assert.equal(service.offers.price,"299.00");
 assert.equal(service.offers.priceCurrency,"USD");
 assert.match(service.description,/up to 20 GitHub Actions workflow files/);
 const json=JSON.stringify(schema);
 assert.doesNotMatch(json,/aggregateRating|reviewCount|FiveStar|InStock|verified customer/i);
 for(const path of ["/case-study","/guides/github-actions-permissions","/guides/release-gate-failure-modes"]){
  const page=await (await visit(path)).text();
  const ld=JSON.parse(page.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)?.[1]);
  assert.ok(ld["@graph"].some(item=>item["@type"]==="TechArticle"),path);
  const breadcrumb=ld["@graph"].find(item=>item["@type"]==="BreadcrumbList");
  assert.ok(breadcrumb,path);
  assert.equal(breadcrumb.itemListElement.at(-1).item,canonicalFor(path));
 }
});

test("XML sitemap has only canonical public information pages, explicit truthful lastmod",async()=>{
 const xml=sitemapXml();
 const response=await visit("/sitemap.xml");
 assert.equal(response.status,200);
 assert.match(response.headers.get("content-type"),/application\/xml/);
 assert.equal(await response.text(),xml);
 const locations=[...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(x=>x[1]);
 assert.equal(locations.length,9);
 assert.equal(new Set(locations).size,9);
 assert.deepEqual(locations,INDEX_PATHS.map(canonicalFor));
 assert.equal((xml.match(/<lastmod>2026-11-16<\/lastmod>/g)||[]).length,9);
 assert.doesNotMatch(xml,/start-review|session_id|checkout\.stripe\.com|api\/|health|privacy|terms/);
 assert.ok(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>'));
 assert.match(xml,/<urlset xmlns="http:\/\/www.sitemaps.org\/schemas\/sitemap\/0.9">/);
});

test("robots.txt advertises canonical sitemap, excludes APIs without blocking noindex intake",async()=>{
 const response=await visit("/robots.txt");
 assert.equal(response.status,200);
 assert.match(response.headers.get("content-type"),/text\/plain/);
 const body=await response.text();
 assert.equal(body,robotsTxt());
 assert.match(body,/User-agent: \*/);
 assert.match(body,/Disallow: \/api\//);
 assert.match(body,/Sitemap: https:\/\/proof.imagineqira.com\/sitemap.xml/);
 assert.doesNotMatch(body,/Disallow: \/start-review/);
});

test("paid intake is noindex, never lists private session IDs in canonical or social metadata",async()=>{
 assert.ok(NON_INDEXABLE.has("/start-review"));
 const token="cs_live_1234567890abcdefghijklmnop";
 const response=await visit("/start-review?session_id="+token);
 assert.equal(response.status,200);
 assert.equal(response.headers.get("x-robots-tag"),"noindex, follow");
 assert.equal(response.headers.get("cache-control"),"no-store");
 assert.equal(response.headers.get("referrer-policy"),"no-referrer");
 const html=await response.text(),head=html.split("</head>")[0];
 assert.match(head,/<meta name="robots" content="noindex,follow">/);
 assert.match(head,/rel="canonical" href="https:\/\/proof.imagineqira.com\/start-review"/);
 assert.doesNotMatch(head,/cs_live_/);
 assert.doesNotMatch(head,/session_id=/);
 assert.ok(!INDEX_PATHS.includes("/start-review"));
});

test("canonical redirects normalize trailing slash while retaining request query safely",async()=>{
 for(const path of ["/case-study/","/methodology/","/guides/"]){
  const response=await visit(path);
  assert.equal(response.status,308);
  assert.equal(response.headers.get("location"),ORIGIN+path.slice(0,-1));
 }
 const slash=await visit("/guides/github-actions-permissions/?from=docs");
 assert.equal(slash.status,308);
 assert.equal(slash.headers.get("location"),ORIGIN+"/guides/github-actions-permissions?from=docs");
});

test("404s remain 404 with noindex; HEAD requests have metadata and no body",async()=>{
 const missing=await visit("/this-page-is-not-real");
 assert.equal(missing.status,404);
 assert.equal(missing.headers.get("x-robots-tag"),"noindex");
 const head=await visit("/case-study",{method:"HEAD"});
 assert.equal(head.status,200);
 assert.equal(await head.text(),"");
 const sm=await visit("/sitemap.xml",{method:"HEAD"});
 assert.equal(sm.status,200);
 assert.equal(await sm.text(),"");
 const robots=await visit("/robots.txt",{method:"HEAD"});
 assert.equal(robots.status,200);
 assert.equal(await robots.text(),"");
});

test("guides contain substantive distinct text, transparent limits, examples and internal references",async()=>{
 assert.equal(GUIDES.length,6);
 for(const page of GUIDES){
  assert.ok(SEO_PAGES[page.slug],page.slug);
  const article=renderGuide(page.slug);
  assert.match(article,/<h1>/);
  assert.match(article,/field-back/);
  assert.match(article,/\/case-study/);
  assert.match(article,/\/guides/);
  const stripped=article.replace(/<[^>]+>/g," ").replace(/\s+/g," ").trim().split(/\s+/);
  assert.ok(stripped.length>210,"Guide too thin: "+page.slug+" ("+stripped.length+" words)");
  if(page.kind==="article"){
   assert.match(article,/Primary reference|Read next|What we observed|Pinned source evidence|Public LOLM example/);
  }
 }
});

test("internal discovery paths connect homepage to methodology, guides, and real source proof",async()=>{
 const home=await (await visit("/")).text();
 for(const p of ["/case-study","/sample-report","/guides","/methodology","/guides/github-actions-permissions","/guides/github-actions-dependency-pinning"])
  assert.ok(home.includes('href="'+p+'"'),"Homepage missing "+p);
 assert.match(home,/Know which control you are reviewing/);
 const caseHtml=await (await visit("/case-study")).text();
 assert.match(caseHtml,/f9700d2e6616/);
 const perm=await (await visit("/guides/github-actions-permissions")).text();
 assert.match(perm,/GITHUB_TOKEN/);
 assert.match(perm,/Workflow syntax/);
 assert.match(perm,/Qira Proof/);
});

test("SEO integration preserves exact Stripe purchase link and verified but unconfigured webhook boundary",async()=>{
 const response=await visit("/");
 const html=await response.text();
 assert.match(html,/id="buyLink"/);
 assert.match(html,/href="https:\/\/buy\.stripe\.com\/9B63cvexo0ts3OBfyv7kc07"/);
 const health=await visit("/health");
 assert.equal((await health.json()).checkout_configured,true);
 const orders=await visit("/api/orders/health");
 assert.equal((await orders.json()).status,"unconfigured");
 const intake=await visit("/start-review");
 assert.match(await intake.text(),/intakeComposer/);
 assert.equal(intake.headers.get("x-robots-tag"),"noindex, follow");
});
