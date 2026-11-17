import {enhanceJourney,JOURNEY_CSS} from "./site_journey.mjs";
// Shared interaction and document styling for every Qira Proof public route.
// Uses the same small typography scale, neutral hierarchy, focused navigation
// and consistent interaction states as the task-first homepage.
export const SITE_CSS=String.raw`
/* V10: one visual system for purchase, examples, proof, guides and legal. */
html{scroll-padding-top:25px}
body{background:#fafbf9;color:#213a35}
:focus-visible{outline:3px solid #476f60!important;outline-offset:3px!important}
.topbar{background:#fafbf9;color:#213a35;border-bottom:1px solid #d8e0da}
.top-inner{min-height:67px}
.logo{font-family:system-ui,Arial,sans-serif;font-weight:780;letter-spacing:-.045em}
.logomark{transform:none!important;border-radius:3px!important;background:#203938!important;color:#fff!important}
.logo small{color:#61766a;letter-spacing:.045em}
.navi{gap:20px}
.navi a{font:600 12px/1.4 system-ui,Arial,sans-serif;text-transform:none;letter-spacing:0;color:#3d564b}
.navi a:hover{color:#8a4935}
.navi .navbuy{color:#fff!important;background:#203938;padding:10px 16px;border-radius:3px}
.navi .navbuy:hover{background:#456559}
.ribbon{display:none!important}
.skip{background:#203938;color:#fff}
footer{background:#233a36;color:#e8f1eb;border-top:1px solid #1e352e}
.footlinks a{font:500 12px/1.6 system-ui,Arial,sans-serif;color:#e3eee7}
.footlinks a:hover{color:#fff;text-decoration:underline}
.footerbar p{font:450 11px system-ui,Arial,sans-serif}
.legal{max-width:1020px;padding:62px 0 100px!important;min-height:58vh}
.legal>.section-headline{font:650 11px/1.5 ui-monospace,monospace;color:#8f513c;text-transform:uppercase;letter-spacing:.065em}
.legal h1{font:400 clamp(43px,5vw,64px)/1.15 Georgia,"Times New Roman",serif;letter-spacing:-.045em;margin:17px 0 27px;text-transform:none;max-width:850px}
.legal h2{font:400 26px/1.3 Georgia,"Times New Roman",serif;letter-spacing:-.03em;margin:35px 0 11px;color:#203a35}
.legal p,.legal li{font:450 15px/1.82 system-ui,Arial,sans-serif;color:#52685f;max-width:820px}
.legal a{color:#8a4a38;text-decoration:underline;text-underline-offset:3px}
.legal p.legal-note{font-size:12px;color:#627c71}
.site-toc{border-block:1px solid #d5e0d6;display:flex;flex-wrap:wrap;gap:9px 21px;padding:16px 0;margin:29px 0 26px;align-items:center}
.site-toc>span{font:650 10px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.06em;color:#6d8576;margin-right:5px}
.site-toc a{font:550 12px/1.45 system-ui,Arial,sans-serif;color:#436e5b;text-decoration:none}
.site-toc a:hover{text-decoration:underline}
.site-route-actions{display:flex;flex-wrap:wrap;gap:13px 22px;margin:39px 0;border-top:1px solid #d5e0d6;padding-top:21px}
.site-route-actions a{font:650 12px system-ui,Arial,sans-serif;color:#476d59;text-decoration:underline;text-underline-offset:3px}
.site-route-actions a:first-child{color:#fff;background:#233e35;padding:12px 16px;text-decoration:none;border-radius:3px}
.report-intro{background:#edf1ed!important;color:#213b35!important;padding:54px 0 52px!important}
.report-intro h1{color:#213b35!important;font:400 clamp(44px,5vw,66px)/1.13 Georgia,"Times New Roman",serif!important;text-transform:none!important;letter-spacing:-.05em!important}
.report-intro .eyebrow{color:#844b3d!important}.report-intro .eyebrow:before{background:#8f4b37!important}
.report-intro p{color:#526d62!important;font:450 16px/1.7 system-ui,Arial,sans-serif!important}
.report-stamp{display:none!important}
.report-stage{padding-top:32px!important}
.report-rail{background:#f3f6f1!important;border:1px solid #d1dfd2!important}
.report-toggles button{border:1px solid #c7d3c8!important;background:#fff!important;color:#2f4b3c!important;border-radius:3px;text-align:left}
.report-toggles button[aria-pressed=true]{border-color:#386951!important;background:#e6f0e7!important}
.report-main{border:1px solid #d1ddd3!important;background:#fff!important}
.report-main-head{background:#f4f7f3!important}
.report-content{background:#fff!important}
.report-content h2{font:400 clamp(29px,3vw,42px)/1.2 Georgia,"Times New Roman",serif!important;letter-spacing:-.04em!important}
.rc-hero,.field-hero{background:#edf1ed!important}
.rc-hero{padding:60px 0 49px!important}
.rc-hero h1{font-size:clamp(44px,5vw,65px)!important}
.rc-intro{font-size:16px!important;max-width:760px!important}
.rc-content{padding-top:26px!important}
.rc-record{scroll-margin-top:20px}
.rc-section{scroll-margin-top:30px}
.rc-overview{display:flex;align-items:center;flex-wrap:wrap;gap:16px 28px;border-bottom:1px solid #cbd8cc;padding:25px 0;margin-bottom:23px}
.rc-overview strong{font:650 12px system-ui,Arial,sans-serif;color:#254036}
.rc-overview span{font:500 12px system-ui,Arial,sans-serif;color:#607a6a}
.rc-jumps{display:flex;flex-wrap:wrap;gap:11px;margin-left:auto}
.rc-jumps a{font:550 12px system-ui,Arial,sans-serif;border:1px solid #bed0c1;border-radius:3px;padding:9px 13px;text-decoration:none;color:#315e49}
.rc-jumps a:hover{background:#e6f0e8}
.field-hero{padding:51px 0 43px!important}
.field-hero h1{font:400 clamp(42px,4.7vw,63px)/1.13 Georgia,"Times New Roman",serif!important;max-width:900px}
.field-intro{font-size:16px!important}
.field-container{padding-top:35px!important}
.field-toc{display:flex;flex-wrap:wrap;gap:10px 18px;border-bottom:1px solid #ccd8d0;padding:0 0 23px;margin-bottom:32px}
.field-toc strong{width:100%;font:650 11px ui-monospace,monospace;text-transform:uppercase;color:#697e70}
.field-toc a{font:550 12px system-ui,Arial,sans-serif;color:#3e6651;text-decoration:underline;text-underline-offset:3px}
.field-section{scroll-margin-top:27px}
.field-section h2{font-size:clamp(27px,3vw,36px)}
.field-cards article{border-top:1px solid #b5c7bb;background:#f1f5ef!important}
.field-cards h3 a{color:#29493a}
.ux-page,.ix-page,.field-page,.rc-page{min-height:58vh}
.ix-form-card:focus-within{border-color:#9ab49e}
.ix-complete{border-color:#8fb49a!important;background:#f1f7f1!important}
.ix-complete h2{color:#234b34}
.ix-complete a{color:#356a4d;text-decoration:underline}
.ix-status{font-size:12px!important}
.ix-status[role="status"]{min-height:21px}
@media(max-width:820px){.navi a:not(.navbuy){display:none!important}.navi{gap:8px}.logo small{display:none}.field-toc{gap:10px 15px}.rc-jumps{width:100%}}
@media(max-width:560px){.legal{padding:37px 0 70px!important}.legal h1{font-size:42px}.legal h2{font-size:25px}.legal p{font-size:14px}.report-intro{padding:38px 0 37px!important}.rc-hero h1{font-size:43px!important}.rc-overview{display:block}.rc-overview span{display:block;margin:7px 0}.rc-jumps{margin:16px 0 0}.field-hero h1{font-size:42px}.field-toc{flex-direction:column;align-items:start}.site-route-actions{flex-direction:column;align-items:start}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto!important}*,:before,:after{transition:none!important;animation:none!important}}
`;
export function addUnifiedShell(html,path){
 const replacement='<nav class="navi" aria-label="Primary"><a href="/">Overview</a><a href="/case-study">Source review</a><a href="/sample-report">Example report</a><a href="/guides">Guides</a><a class="navbuy" href="/#start">Start review →</a></nav>';
 const start=html.indexOf('<nav class="navi" aria-label="Primary">');
 const end=start>=0?html.indexOf("</nav>",start):-1;
 if(start>=0&&end>start)html=html.slice(0,start)+replacement+html.slice(end+6);
 return enhanceJourney(html,path).replace("</style></head>",SITE_CSS+JOURNEY_CSS+"</style></head>");
}
export function addLegalNavigation(html){
 const result=html.replace(new RegExp("<h2>([^<]+)</h2>","g"),(_whole,label)=>{
  const id="section-"+label.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
  return '<h2 id="'+id+'">'+label+'</h2>';
 });
 const headings=[...result.matchAll(new RegExp('<h2 id="([^"]+)">([^<]+)</h2>',"g"))];
 if(!headings.length)return result;
 const links=headings.slice(0,7).map(m=>'<a href="#'+m[1]+'">'+m[2]+'</a>').join("");
 return result.replace("</h1>",'</h1><nav class="site-toc" aria-label="On this page"><span>On this page</span>'+links+'</nav>');
}
