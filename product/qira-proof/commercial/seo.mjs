import {GUIDES} from "./guides.mjs";
export const ORIGIN="https://proof.imagineqira.com";
export const PUBLISHED="2026-11-16";
export const INDEX_PATHS=[
 "/", "/case-study", "/sample-report", "/methodology", "/guides",
 "/guides/github-actions-permissions",
 "/guides/github-actions-dependency-pinning",
 "/guides/ssh-host-key-verification",
 "/guides/release-gate-failure-modes"
];
const custom={
 "/":{
  title:"GitHub Actions Security Configuration Review | Qira Proof",
  description:"Human-reviewed GitHub Actions security configuration assessment. One repository, up to 20 workflows, source-linked findings. $299 one-time founding review.",
  kind:"service"
 },
 "/case-study":{
  title:"Real GitHub Actions Security Findings: LOLM Case Study | Qira Proof",
  description:"Five source-backed observations from a pinned LOLM release workflow: three corroborated YAML findings and two separately documented manual control-flow reviews.",
  kind:"article"
 },
 "/sample-report":{
  title:"Example GitHub Actions Review Report | Qira Proof",
  description:"Explore an explicitly synthetic GitHub Actions security review report with source excerpts, evidence limits, review recommendations and coverage boundaries.",
  kind:"webpage"
 },
 "/privacy":{
  title:"Privacy and Data Handling | Qira Proof",
  description:"How Qira Proof handles repository review information, Stripe-hosted payments, customer intake and limitations of the public preview.",
  kind:"webpage"
 },
 "/terms":{
  title:"Founding Review Scope and Terms | Qira Proof",
  description:"Scope and limits of Qira Proof's $299 one-time GitHub Actions workflow review, human fulfillment, returns and customer responsibilities.",
  kind:"webpage"
 }
};
for(const page of GUIDES){
 const title=page.slug==="/methodology"?"GitHub Actions Review Methodology | Qira Proof":page.title+" | Qira Proof";
 custom[page.slug]={title,description:page.desc,kind:page.kind==="article"?"article":page.kind==="index"?"collection":"webpage"};
}
export const SEO_PAGES=Object.freeze(custom);
export const NON_INDEXABLE=new Set(["/start-review"]);
const xmlEscape=s=>String(s).replace(/[<>&"']/g,c=>({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;","'":"&apos;"}[c]));
const htmlEscape=s=>String(s).replace(/[<>&"']/g,c=>({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;","'":"&#39;"}[c]));
const jsonLdSafe=v=>JSON.stringify(v).replace(/</g,"\\u003c").replace(/>/g,"\\u003e").replace(/&/g,"\\u0026");
export const canonicalFor=path=>ORIGIN+(path==="/"?"/":path);
const org={"@type":"Organization","@id":ORIGIN+"/#organization",name:"Qira",url:"https://imagineqira.com/",parentOrganization:{"@type":"Organization",name:"ImagineQira",url:"https://imagineqira.com/"}};
const website={"@type":"WebSite","@id":ORIGIN+"/#website",name:"Qira Proof",url:ORIGIN+"/",publisher:{"@id":org["@id"]},inLanguage:"en-US"};
const breadcrumb=path=>{
 if(path==="/")return null;
 const current=SEO_PAGES[path]?.title.split(" | Qira Proof")[0]||"Qira Proof";
 const items=[{"@type":"ListItem",position:1,name:"Qira Proof",item:ORIGIN+"/"}];
 if(path.startsWith("/guides/"))items.push({"@type":"ListItem",position:2,name:"Field notes",item:ORIGIN+"/guides"});
 items.push({"@type":"ListItem",position:items.length+1,name:current,item:canonicalFor(path)});
 return {"@type":"BreadcrumbList","@id":canonicalFor(path)+"#breadcrumb",itemListElement:items};
};
function pageGraph(path,meta){
 const url=canonicalFor(path);
 const isArticle=meta.kind==="article";
 const page={"@type":meta.kind==="collection"?"CollectionPage":isArticle?"WebPage":"WebPage",
  "@id":url+"#webpage",url,name:meta.title,description:meta.description,
  isPartOf:{"@id":website["@id"]},inLanguage:"en-US"};
 if(path!=="/"){page.dateModified=PUBLISHED;page.datePublished=PUBLISHED;}
 const graph=[page];
 if(path==="/"){
  graph.unshift(org,website);
  graph.push({
   "@type":"Service","@id":url+"#founding-review",
   name:"Qira Proof Founding Workflow Review",
   serviceType:"GitHub Actions workflow configuration review",
   provider:{"@id":org["@id"]},
   url,
   description:"One authorized GitHub repository; up to 20 GitHub Actions workflow files; human-reviewed source-linked observations and written recommendations.",
   offers:{"@type":"Offer",url:ORIGIN+"/#pricing",price:"299.00",priceCurrency:"USD",
    description:"One-time founding workflow review, tax-inclusive where applicable; charged by Trend through Stripe."}
  });
 }else{
  const bc=breadcrumb(path);if(bc)graph.push(bc);
  if(isArticle){
   const isCase=path==="/case-study";
   graph.push({"@type":"TechArticle","@id":url+"#article",headline:meta.title.replace(/ \| Qira Proof$/,""),
    description:meta.description,mainEntityOfPage:{"@id":url+"#webpage"},
    author:{"@id":org["@id"]},publisher:{"@id":org["@id"]},
    datePublished:PUBLISHED,dateModified:PUBLISHED,inLanguage:"en-US",
    ...(isCase?{isBasedOn:"https://github.com/TheArtOfSound/lolm/commit/f9700d2e661640da4a8d0cf2bb9c046d77f8a06b"}:{})
   });
  }
 }
 return {"@context":"https://schema.org","@graph":graph};
}
export function applySEO(html,path){
 const meta=SEO_PAGES[path];
 if(!meta)return html;
 const canonical=canonicalFor(path);
 const title=htmlEscape(meta.title),description=htmlEscape(meta.description),url=htmlEscape(canonical);
 let output=html.replace(/<title>[^<]*<\/title>/,"<title>"+title+"</title>");
 output=output.replace(/<meta name="description" content="[^"]*">/,'<meta name="description" content="'+description+'">');
 output=output.replace(/<meta name="theme-color" content="[^"]*">/,'<meta name="theme-color" content="#203437">');
 const indexing=NON_INDEXABLE.has(path)?'<meta name="robots" content="noindex,follow">':'<meta name="robots" content="index,follow,max-image-preview:large">';
 const tags=[
  '<link rel="canonical" href="'+url+'">',
  indexing,
  '<meta property="og:type" content="'+(meta.kind==="article"?"article":"website")+'">',
  '<meta property="og:site_name" content="Qira Proof">',
  '<meta property="og:locale" content="en_US">',
  '<meta property="og:title" content="'+title+'">',
  '<meta property="og:description" content="'+description+'">',
  '<meta property="og:url" content="'+url+'">',
  '<meta name="twitter:card" content="summary">',
  '<meta name="twitter:title" content="'+title+'">',
  '<meta name="twitter:description" content="'+description+'">',
  '<script type="application/ld+json">'+jsonLdSafe(pageGraph(path,meta))+'</script>'
 ].join("\n");
 return output.replace("</head>",tags+"</head>");
}
export function robotsTxt(){
 return [
  "User-agent: *",
  "Allow: /",
  "Disallow: /api/",
  "",
  "Sitemap: "+ORIGIN+"/sitemap.xml",
  ""
 ].join("\n");
}
export function sitemapXml(){
 return '<?xml version="1.0" encoding="UTF-8"?>\n'
 +'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
 +INDEX_PATHS.map(path=>'  <url><loc>'+xmlEscape(canonicalFor(path))+'</loc><lastmod>'+PUBLISHED+'</lastmod></url>').join("\n")
 +'\n</urlset>\n';
}
