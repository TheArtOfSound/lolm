// Qira Proof V11: progressive navigation, local context and next steps.
const ROUTES=[["/","Overview"],["/case-study","Real source review"],["/sample-report","Example report"],["/methodology","Methodology"],["/guides","Security guides"],["/start-review","Paid intake"],["/privacy","Privacy"],["/terms","Service terms"]];
const GUIDES={"/guides/github-actions-permissions":"Token permissions","/guides/github-actions-dependency-pinning":"Action pinning","/guides/ssh-host-key-verification":"SSH trust","/guides/release-gate-failure-modes":"Release gates"};
const safe=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const active=(p,h)=>p===h||(h==="/guides"&&p.startsWith("/guides/"));
function nextLinks(path){
 if(path==="/case-study")return [["/sample-report","See a report"],["/#start","Review my repository"]];
 if(path==="/sample-report")return [["/case-study","Real source review"],["/#start","Review my repository"]];
 if(path==="/methodology")return [["/case-study","See the method applied"],["/#start","Start my review"]];
 if(path==="/guides"||path.startsWith("/guides/"))return [["/guides","All field notes"],["/case-study","Real evidence"],["/#start","Apply to my repository"]];
 if(path==="/terms"||path==="/privacy")return [["/terms","Service terms"],["/privacy","Privacy"],["/#start","Start review"]];
 return [];
}
export function enhanceJourney(html,path){
 const title=ROUTES.find(([u])=>u===path)?.[1]||GUIDES[path];
 let nav='<nav class="navi" aria-label="Primary">';
 for(const [url,label]of ROUTES.filter(([u])=>["/","/case-study","/sample-report","/guides"].includes(u)))
  nav+='<a href="'+url+'"'+(active(path,url)?' aria-current="page"':'')+'>'+safe(label)+'</a>';
 nav+='<a class="navbuy" href="/#start">Start review →</a></nav>';
 let menu='<details class="site-menu"><summary>Menu</summary><div class="site-menu-links">';
 for(const [url,label]of ROUTES)menu+='<a href="'+url+'"'+(active(path,url)?' aria-current="page"':'')+'>'+safe(label)+'</a>';
 menu+='</div></details>';
 const i=html.indexOf('<nav class="navi" aria-label="Primary">'),j=i>=0?html.indexOf("</nav>",i):-1;
 if(i>=0&&j>i)html=html.slice(0,i)+nav+menu+html.slice(j+6);
 if(path!=="/"&&title){
  let breadcrumb='<nav class="site-path" aria-label="Breadcrumb"><div class="shell site-path-inner"><a href="/">Qira Proof</a><span>/</span>';
  if(path.startsWith("/guides/"))breadcrumb+='<a href="/guides">Guides</a><span>/</span>';
  breadcrumb+='<strong aria-current="page">'+safe(title)+'</strong></div></nav>';
  html=html.replace('<main id="main">',breadcrumb+'<main id="main">');
  if(path==="/case-study")html=html.replace('<div class="rc-meta">','<p class="site-jump"><a href="#rcWorkflow">Jump to the actual findings ↓</a></p><div class="rc-meta">');
  const actions=nextLinks(path);
  if(actions.length){
   const links=actions.map(([u,l])=>'<a href="'+u+'">'+safe(l)+'</a>').join("");
   const block='<aside class="site-next" aria-label="Related actions"><div class="shell site-next-inner"><div><h2>Where next?</h2><p>Continue reading or begin a review of your own repository.</p></div><div class="site-next-links">'+links+'</div></div></aside>';
   html=html.replace('</main>',block+'</main>');
  }
 }
 return html;
}
export const JOURNEY_CSS="\n.top-inner{position:relative}\n.site-menu{display:none;position:relative;z-index:35}\n.site-menu summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;padding:9px 11px;border:1px solid #cad8ce;border-radius:3px;color:#294839;font:650 12px/1.4 system-ui,Arial,sans-serif}\n.site-menu summary::-webkit-details-marker{display:none}\n.site-menu summary:after{content:\"⌄\";font-size:15px}\n.site-menu[open] summary:after{content:\"⌃\"}\n.site-menu-links{display:grid;position:absolute;right:0;top:calc(100% + 10px);min-width:210px;padding:8px;gap:3px;background:#fff;border:1px solid #cbd8cd;border-radius:4px;box-shadow:0 18px 34px #16372924;z-index:40}\n.site-menu-links a{font:600 13px/1.5 system-ui,Arial,sans-serif;color:#294939;padding:10px 13px;text-decoration:none;border-radius:3px}\n.site-menu-links a:hover,.site-menu-links a:focus-visible,.site-menu-links a[aria-current=page]{background:#eaf2eb;color:#153b29}\n.navi a[aria-current=page]:not(.navbuy){text-decoration:underline;text-underline-offset:7px;text-decoration-color:#91ae9a}\n.site-path{background:#fafbf9;border-bottom:1px solid #e0e7df}\n.site-path-inner{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:10px 0;font:550 11px/1.4 system-ui,Arial,sans-serif;color:#7c8e7f}\n.site-path a{color:#436b54;text-underline-offset:3px}\n.site-path strong{font-weight:650;color:#2d4f3b}\n.site-next{background:#ecf2ec;border-block:1px solid #cbd9cc;padding:37px 0}\n.site-next-inner{display:flex;align-items:center;justify-content:space-between;gap:24px}\n.site-next h2{font:400 clamp(26px,3vw,34px)/1.2 Georgia,serif;letter-spacing:-.03em;margin:0 0 8px;color:#284338}\n.site-next p{font:450 13px/1.65 system-ui,Arial,sans-serif;margin:0;color:#607668;max-width:560px}\n.site-next-links{display:flex;flex-wrap:wrap;align-items:center;gap:9px}\n.site-next-links a{font:650 12px system-ui,Arial,sans-serif;text-decoration:none;border:1px solid #b6cbbb;background:#fff;color:#305942;padding:12px 14px;border-radius:3px}\n.site-next-links a:last-child{background:#294b3b;color:#fff;border-color:#294b3b}\n.site-next-links a:hover{text-decoration:underline}\n.site-jump{margin:14px 0 23px}.site-jump a{font:650 13px/1.5 system-ui,Arial,sans-serif;color:#356c4c;text-underline-offset:3px}\n@media(max-width:900px){.site-next-inner{flex-direction:column;align-items:start}.site-next-links{width:100%}}\n@media(max-width:820px){.site-menu{display:block}.top-inner{gap:7px}.navi{margin-left:auto}}\n@media(max-width:560px){\n .site-path-inner{padding:9px 0;font-size:10px}\n .site-next{padding:28px 0 34px}.site-next-links{display:grid;grid-template-columns:1fr;width:100%}.site-next-links a{text-align:center}\n .report-stage{padding-top:17px!important}\n .report-rail{padding:12px!important}.report-rail h2{margin:0 0 8px!important;font-size:10px!important}.report-rail>p{font-size:11px!important;line-height:1.35!important;margin:8px 0 0!important}\n .report-toggles{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important}\n .report-toggles button{min-width:0!important;min-height:60px!important;padding:9px 5px!important;font-size:11px!important;line-height:1.3!important;text-align:center!important}\n .report-toggles button small{display:block!important;font-size:9px!important;letter-spacing:0!important}\n .report-content{padding-top:16px!important}\n .rc-hero,.field-hero{padding-top:36px!important}.legal{padding-top:26px!important}\n}\n";
