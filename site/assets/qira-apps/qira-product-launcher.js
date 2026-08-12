/*! Qira Product Launcher v1.0.0 — generated from canonical registry 917e64480639ae06ac14a7042a485ba2dfa1319e
 * Do not edit by hand. Run: node packages/qira-navigation/scripts/generate.mjs
 */
(function () {
  "use strict";
  if (customElements.get("qira-product-launcher")) return;

  var LAUNCHER_VERSION = "1.0.0";
  var ALLOWED = ["flows","oort","qev","lolm","aex","ledger"];
  var BUNDLED = {"products":[{"id":"flows","name":"Flows","shortDescription":"Build · verify · recover","tooltip":"Builds software through controlled steps and tracks the evidence supporting the result.","url":"https://flows.oortstack.com","icon":"flows","accentColor":"#1f6bb5","accentSoft":"#dbeafe","markInitial":"F","status":"live","order":1,"visibleInLauncher":true},{"id":"oort","name":"Oort","shortDescription":"Account · models · usage","tooltip":"Manages your Qira account, AI providers, models, access, and usage.","url":"https://oortstack.com","icon":"oort","accentColor":"#f97316","accentSoft":"#ffedd5","markInitial":"O","status":"live","order":2,"visibleInLauncher":true},{"id":"qev","name":"QEV","shortDescription":"Protect · prove · verify","tooltip":"Protects digital files and provides evidence that they remain unchanged.","url":"https://secure.imagineqira.com","icon":"qev","accentColor":"#0f766e","accentSoft":"#ccfbf1","markInitial":"Q","status":"live","order":3,"visibleInLauncher":true},{"id":"lolm","name":"LOLM","shortDescription":"Persistent AI operations","tooltip":"Keeps operational context and failed-attempt memory across long-running AI work.","url":"https://lolm.imagineqira.com","icon":"lolm","accentColor":"#6366f1","accentSoft":"#e0e7ff","markInitial":"L","status":"research","order":4,"visibleInLauncher":true},{"id":"ledger","name":"Ledger","shortDescription":"AI work · usage · records","tooltip":"Records AI work, usage, and operational history across Qira products.","url":"https://ledger.imagineqira.com","icon":"ledger","accentColor":"#22c55e","accentSoft":"#dcfce7","markInitial":"Ld","status":"live","order":5,"visibleInLauncher":true},{"id":"aex","name":"AEX","shortDescription":"Measure · verify · energy","tooltip":"Measures AI workload energy, verifies claims against a baseline, and seals evidence records.","url":"https://imagineqira.com/aex/","icon":"aex","accentColor":"#00e8c0","accentSoft":"#ccfbf1","markInitial":"A","status":"live","order":6,"visibleInLauncher":true}],"allowlist":["https://flows.oortstack.com","https://oortstack.com","https://secure.imagineqira.com","https://lolm.imagineqira.com","https://ledger.imagineqira.com","https://imagineqira.com"]};
  var STYLES = "/* Generated for shadow DOM host isolation — classes use qira-launcher__ prefix */\n/**\n * Qira Apps launcher — Google-style app grid.\n * Clean circular trigger, soft elevated panel, 3-column icon grid.\n * Self-contained (no Tailwind). Hosts may override via CSS variables.\n */\n\n.qira-launcher {\n  /* Surfaces */\n  --ql-bg: #ffffff;\n  --ql-panel: #ffffff;\n  --ql-border: rgba(60, 64, 67, 0.12);\n  --ql-text: #202124;\n  --ql-muted: #5f6368;\n  --ql-muted2: #80868b;\n  --ql-hover: #f1f3f4;\n  --ql-scrim: rgba(32, 33, 36, 0.4);\n  --ql-focus: #1a73e8;\n  --ql-here-bg: #e8f0fe;\n  --ql-here-fg: #1967d2;\n  --ql-soon-bg: #f1f3f4;\n  --ql-soon-fg: #5f6368;\n  --ql-tile-border: transparent;\n  --ql-icon-bg: #f1f3f4;\n  --ql-icon-fg: #3c4043;\n  /* Soft multi-layer elevation (Google-like) */\n  --ql-shadow:\n    0 1px 2px rgba(60, 64, 67, 0.15),\n    0 2px 6px 2px rgba(60, 64, 67, 0.1);\n  --ql-radius: 28px;\n  --ql-trigger-border: transparent;\n  --ql-trigger-fg: #5f6368;\n  --ql-trigger-hover-bg: #f1f3f4;\n  --ql-trigger-hover-fg: #202124;\n  --ql-trigger-active-bg: #e8eaed;\n  position: relative;\n  flex-shrink: 0;\n  font-family: \"Google Sans\", Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif;\n  -webkit-font-smoothing: antialiased;\n}\n\n.qira-launcher[data-theme=\"dark\"] {\n  --ql-bg: #202124;\n  --ql-panel: #292a2d;\n  --ql-border: rgba(255, 255, 255, 0.1);\n  --ql-text: #e8eaed;\n  --ql-muted: #9aa0a6;\n  --ql-muted2: #80868b;\n  --ql-hover: #3c4043;\n  --ql-scrim: rgba(0, 0, 0, 0.55);\n  --ql-focus: #8ab4f8;\n  --ql-here-bg: rgba(138, 180, 248, 0.16);\n  --ql-here-fg: #8ab4f8;\n  --ql-soon-bg: rgba(154, 160, 166, 0.16);\n  --ql-soon-fg: #9aa0a6;\n  --ql-tile-border: transparent;\n  --ql-icon-bg: #3c4043;\n  --ql-icon-fg: #e8eaed;\n  --ql-shadow:\n    0 1px 3px 0 rgba(0, 0, 0, 0.4),\n    0 4px 8px 3px rgba(0, 0, 0, 0.25);\n  --ql-trigger-border: transparent;\n  --ql-trigger-fg: #9aa0a6;\n  --ql-trigger-hover-bg: #3c4043;\n  --ql-trigger-hover-fg: #e8eaed;\n  --ql-trigger-active-bg: #5f6368;\n}\n\n/* ── Trigger: circular 3×3 grid, no chrome ── */\n.qira-launcher__trigger {\n  display: inline-flex;\n  height: 2.5rem;\n  width: 2.5rem;\n  min-height: 2.5rem;\n  min-width: 2.5rem;\n  align-items: center;\n  justify-content: center;\n  border-radius: 50%;\n  border: 0;\n  background: transparent;\n  color: var(--ql-trigger-fg);\n  cursor: pointer;\n  -webkit-tap-highlight-color: transparent;\n  touch-action: manipulation;\n  transition: background-color 0.12s ease, color 0.12s ease;\n}\n\n.qira-launcher__trigger:hover {\n  background: var(--ql-trigger-hover-bg);\n  color: var(--ql-trigger-hover-fg);\n}\n\n.qira-launcher__trigger:active {\n  background: var(--ql-trigger-active-bg);\n}\n\n.qira-launcher__trigger:focus-visible {\n  outline: 2px solid var(--ql-focus);\n  outline-offset: 2px;\n}\n\n.qira-launcher__trigger[aria-expanded=\"true\"] {\n  background: var(--ql-trigger-hover-bg);\n  color: var(--ql-trigger-hover-fg);\n}\n\n/* ── Desktop panel ── */\n.qira-launcher__panel {\n  position: absolute;\n  right: 0;\n  top: calc(100% + 0.5rem);\n  z-index: 50;\n  width: min(100vw - 1.5rem, 20.5rem);\n  max-width: calc(100vw - 1.5rem);\n  /* visible so tips aren't clipped; grid handles its own scroll */\n  overflow: visible;\n  border-radius: var(--ql-radius);\n  border: 1px solid var(--ql-border);\n  background: var(--ql-panel);\n  box-shadow: var(--ql-shadow);\n  box-sizing: border-box;\n  /* Opacity-only open — transform creates a containing block that traps fixed tips */\n  animation: qira-launcher-pop 0.14s ease-out;\n}\n\n@keyframes qira-launcher-pop {\n  from {\n    opacity: 0;\n  }\n  to {\n    opacity: 1;\n  }\n}\n\n.qira-launcher__header {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 0.75rem;\n  border-bottom: 0;\n  padding: 1rem 1.25rem 0.35rem;\n}\n\n.qira-launcher__title {\n  margin: 0;\n  font-size: 0.9375rem;\n  font-weight: 500;\n  letter-spacing: 0;\n  color: var(--ql-text);\n  line-height: 1.35;\n}\n\n.qira-launcher__close {\n  display: none;\n  align-items: center;\n  justify-content: center;\n  height: 2.25rem;\n  width: 2.25rem;\n  min-height: 2.25rem;\n  min-width: 2.25rem;\n  padding: 0;\n  border: 0;\n  border-radius: 50%;\n  background: transparent;\n  color: var(--ql-muted);\n  cursor: pointer;\n  box-sizing: border-box;\n  transition: background-color 0.12s ease, color 0.12s ease;\n}\n\n.qira-launcher__close:hover {\n  background: var(--ql-hover);\n  color: var(--ql-text);\n}\n\n.qira-launcher__close:focus-visible {\n  outline: 2px solid var(--ql-focus);\n  outline-offset: 2px;\n}\n\n/* 3-column Google-style grid */\n.qira-launcher__grid {\n  display: grid;\n  grid-template-columns: repeat(3, 1fr);\n  gap: 0.15rem 0.25rem;\n  padding: 0.5rem 0.85rem 1.1rem;\n  box-sizing: border-box;\n}\n\n/* ── Tile: icon above label, no card chrome ── */\n.qira-launcher__tile {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  justify-content: flex-start;\n  gap: 0.45rem;\n  min-height: 0;\n  min-width: 0;\n  padding: 0.65rem 0.35rem 0.55rem;\n  border-radius: 1rem;\n  border: 0;\n  background: transparent;\n  color: inherit;\n  text-align: center;\n  text-decoration: none;\n  cursor: pointer;\n  transition: background-color 0.12s ease;\n  box-sizing: border-box;\n}\n\na.qira-launcher__tile:hover,\n.qira-launcher__tile:hover {\n  background: var(--ql-hover);\n}\n\n.qira-launcher__tile:focus-visible {\n  outline: 2px solid var(--ql-focus);\n  outline-offset: 1px;\n}\n\n.qira-launcher__tile--current {\n  background: color-mix(in srgb, var(--ql-focus) 8%, transparent);\n}\n\n.qira-launcher__tile--current:hover {\n  background: color-mix(in srgb, var(--ql-focus) 12%, transparent);\n}\n\n.qira-launcher__tile--disabled {\n  cursor: not-allowed;\n  opacity: 0.55;\n}\n\n.qira-launcher__tile--disabled:hover {\n  background: transparent;\n}\n\n.qira-launcher__tile-top {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  justify-content: center;\n  width: 100%;\n  position: relative;\n  gap: 0;\n}\n\n/* Soft rounded-square app icon */\n.qira-launcher__icon {\n  display: inline-flex;\n  height: 3.25rem;\n  width: 3.25rem;\n  flex-shrink: 0;\n  align-items: center;\n  justify-content: center;\n  border-radius: 1.1rem;\n  /* Soft brand plate when product sets --ql-product-soft; else neutral */\n  background: var(--ql-product-soft, var(--ql-icon-bg));\n  color: var(--ql-icon-fg);\n  transition: box-shadow 0.12s ease, transform 0.12s ease;\n  /* Avoid layout shift while mark paints */\n  overflow: hidden;\n  aspect-ratio: 1 / 1;\n}\n\n.qira-launcher__tile:hover .qira-launcher__icon {\n  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.12);\n}\n\n.qira-launcher__tile--current .qira-launcher__icon {\n  box-shadow: 0 0 0 2px color-mix(in srgb, var(--ql-product-accent, var(--ql-focus)) 70%, transparent);\n}\n\n/* Full-color product marks fill the plate (real brand artwork, not mono strokes) */\n.qira-launcher__icon svg {\n  width: 1.75rem;\n  height: 1.75rem;\n  display: block;\n  flex-shrink: 0;\n}\n\n/* Dark theme: keep full-color marks; soften plate slightly */\n.qira-launcher[data-theme=\"dark\"] .qira-launcher__icon {\n  background: color-mix(in srgb, var(--ql-product-accent, #9aa0a6) 22%, #3c4043);\n}\n\n/* Status sits under the name as a micro-label, not a corner chip */\n.qira-launcher__badge {\n  display: inline-flex;\n  align-items: center;\n  justify-content: center;\n  border-radius: 999px;\n  padding: 0.1rem 0.4rem;\n  font-size: 0.625rem;\n  font-weight: 500;\n  line-height: 1.2;\n  white-space: nowrap;\n  letter-spacing: 0.01em;\n  max-width: 100%;\n  overflow: hidden;\n  text-overflow: ellipsis;\n}\n\n.qira-launcher__badge--here {\n  background: var(--ql-here-bg);\n  color: var(--ql-here-fg);\n}\n\n.qira-launcher__badge--soon {\n  background: var(--ql-soon-bg);\n  color: var(--ql-soon-fg);\n}\n\n.qira-launcher__badge--research {\n  background: color-mix(in srgb, #7c3aed 14%, transparent);\n  color: #6d28d9;\n}\n\n.qira-launcher[data-theme=\"dark\"] .qira-launcher__badge--research {\n  background: color-mix(in srgb, #a78bfa 20%, transparent);\n  color: #c4b5fd;\n}\n\n.qira-launcher__name {\n  margin: 0;\n  font-size: 0.8125rem;\n  font-weight: 400;\n  color: var(--ql-text);\n  line-height: 1.25;\n  max-width: 100%;\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n/* Description hidden in Google-style grid — available via tooltip / aria */\n.qira-launcher__desc {\n  display: none;\n  margin: 0;\n  font-size: 0.6875rem;\n  color: var(--ql-muted);\n  line-height: 1.3;\n}\n\n.qira-launcher__meta {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  gap: 0.2rem;\n  width: 100%;\n  min-width: 0;\n}\n\n/* Tooltip wrap — tips themselves render in a body portal (fixed) */\n.qira-launcher__tooltip-wrap {\n  position: relative;\n  display: block;\n  width: 100%;\n}\n\n/*\n * High-contrast tip: always solid light surface + dark text so it stays\n * readable on both light and dark host themes (Ledger dark was unreadable).\n */\n.qira-launcher__tooltip,\n.qira-launcher__tooltip--portal {\n  box-sizing: border-box;\n  z-index: 2147483646;\n  width: max-content;\n  max-width: min(17.5rem, calc(100vw - 1rem));\n  padding: 0.55rem 0.7rem;\n  border-radius: 0.5rem;\n  border: 1px solid rgba(60, 64, 67, 0.2);\n  background: #ffffff;\n  color: #202124;\n  font-family: Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif;\n  font-size: 0.8125rem;\n  font-weight: 400;\n  line-height: 1.4;\n  letter-spacing: 0;\n  white-space: normal;\n  overflow-wrap: anywhere;\n  word-break: break-word;\n  box-shadow:\n    0 1px 2px rgba(60, 64, 67, 0.2),\n    0 4px 12px rgba(60, 64, 67, 0.18);\n  pointer-events: none;\n  text-align: left;\n}\n\n/* Fallback in-panel tip (if portal unavailable) — place below tile, never clipped */\n.qira-launcher__tooltip:not(.qira-launcher__tooltip--portal) {\n  position: absolute;\n  left: 50%;\n  top: calc(100% + 0.4rem);\n  bottom: auto;\n  transform: translateX(-50%);\n  z-index: 80;\n}\n\n.qira-launcher__tooltip[hidden] {\n  display: none !important;\n}\n\n/* Scrim — desktop: invisible hit-area off; mobile: dimmed */\n.qira-launcher__scrim {\n  display: none;\n}\n\n/*\n * Body-portal surface (Web Component / React mobile open).\n * Escapes sticky/backdrop-filter containing blocks.\n */\n.qira-launcher--portal {\n  position: fixed;\n  inset: 0;\n  width: 100%;\n  height: 100%;\n  max-width: none;\n  z-index: 2147483000;\n  pointer-events: none;\n  font-family: \"Google Sans\", Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif;\n}\n\n.qira-launcher--portal .qira-launcher__scrim,\n.qira-launcher--portal .qira-launcher__panel {\n  pointer-events: auto;\n}\n\n.qira-launcher[data-open=\"true\"].qira-launcher--portal {\n  position: fixed !important;\n  inset: 0 !important;\n  z-index: 2147483000 !important;\n}\n\n@media (max-width: 640px) {\n  .qira-launcher__trigger {\n    height: 44px;\n    width: 44px;\n    min-height: 44px;\n    min-width: 44px;\n  }\n\n  .qira-launcher__scrim {\n    display: block;\n    position: fixed;\n    inset: 0;\n    z-index: 2147483000;\n    border: 0;\n    margin: 0;\n    padding: 0;\n    width: 100%;\n    height: 100%;\n    background: var(--ql-scrim);\n    cursor: pointer;\n    -webkit-tap-highlight-color: transparent;\n  }\n\n  .qira-launcher--portal .qira-launcher__scrim {\n    position: absolute;\n    z-index: 1;\n  }\n\n  .qira-launcher__panel {\n    position: fixed;\n    left: 0.75rem;\n    right: 0.75rem;\n    top: auto;\n    bottom: max(0.75rem, env(safe-area-inset-bottom, 0px));\n    z-index: 2147483001;\n    width: auto;\n    max-width: none;\n    max-height: min(78dvh, 32rem);\n    border-radius: 1.5rem;\n    overflow: visible;\n    display: flex;\n    flex-direction: column;\n    overscroll-behavior: contain;\n    padding-bottom: 0;\n    box-sizing: border-box;\n    /* opacity only — no transform (traps fixed tooltips) */\n    animation: qira-launcher-sheet 0.18s ease-out;\n  }\n\n  @keyframes qira-launcher-sheet {\n    from {\n      opacity: 0;\n    }\n    to {\n      opacity: 1;\n    }\n  }\n\n  .qira-launcher--portal .qira-launcher__panel {\n    position: absolute;\n    z-index: 2;\n  }\n\n  .qira-launcher__header {\n    flex-shrink: 0;\n    padding: 1.1rem 1rem 0.25rem;\n    padding-left: max(1rem, env(safe-area-inset-left, 0px));\n    padding-right: max(0.5rem, env(safe-area-inset-right, 0px));\n  }\n\n  .qira-launcher__close {\n    display: inline-flex;\n  }\n\n  .qira-launcher__grid {\n    flex: 1 1 auto;\n    min-height: 0;\n    overflow-y: auto;\n    overflow-x: hidden;\n    -webkit-overflow-scrolling: touch;\n    overscroll-behavior: contain;\n    grid-template-columns: repeat(3, 1fr);\n    gap: 0.25rem;\n    padding: 0.5rem 0.65rem 1.15rem;\n    padding-left: max(0.65rem, env(safe-area-inset-left, 0px));\n    padding-right: max(0.65rem, env(safe-area-inset-right, 0px));\n    box-sizing: border-box;\n  }\n\n  .qira-launcher__tile {\n    min-width: 0;\n    padding: 0.7rem 0.25rem 0.55rem;\n  }\n\n  .qira-launcher__icon {\n    height: 3.5rem;\n    width: 3.5rem;\n    border-radius: 1.15rem;\n  }\n\n  .qira-launcher__name {\n    font-size: 0.75rem;\n    white-space: normal;\n    display: -webkit-box;\n    -webkit-line-clamp: 2;\n    -webkit-box-orient: vertical;\n    overflow: hidden;\n  }\n\n  .qira-launcher__tooltip,\n  .qira-launcher__tooltip--portal {\n    max-width: min(17.5rem, calc(100vw - 1rem));\n    font-size: 0.8125rem;\n  }\n}\n\n/* Very narrow: keep 3 cols if possible; only drop to 2 under 300px */\n@media (max-width: 300px) {\n  .qira-launcher__grid {\n    grid-template-columns: repeat(2, 1fr);\n  }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  .qira-launcher__trigger,\n  .qira-launcher__tile,\n  .qira-launcher__close,\n  .qira-launcher__icon {\n    transition: none;\n  }\n\n  .qira-launcher__panel {\n    animation: none;\n  }\n}\n";

  function isAllowed(id) { return ALLOWED.indexOf(id) !== -1; }

  function sanitize(products, allowlist) {
    if (!products || products.length !== 6) throw new Error("need 6 products");
    var seen = {};
    var out = [];
    for (var i = 0; i < products.length; i++) {
      var p = products[i];
      if (!isAllowed(p.id)) throw new Error("unknown id");
      if (seen[p.id]) throw new Error("dup");
      seen[p.id] = 1;
      var blob = (p.name + p.shortDescription + p.tooltip + (p.icon||"")).toLowerCase();
      if (blob.indexOf("we" + "search") !== -1) throw new Error("forbidden product name");
      if (p.id === "aex" && p.url) {
        var aexU = new URL(p.url);
        if (aexU.origin !== "https://imagineqira.com") throw new Error("aex host");
        if (aexU.pathname.indexOf("/aex") !== 0) throw new Error("aex path");
      }
      if (p.url) {
        var u = new URL(p.url);
        if (u.protocol !== "https:") throw new Error("proto");
        if (u.hostname === "ledger.com" || u.hostname === "www.ledger.com") throw new Error("blocked");
        if (p.id === "ledger" && u.hostname.indexOf("ledger.com") !== -1) throw new Error("ledger.com");
        var ok = false;
        for (var j = 0; j < allowlist.length; j++) {
          if (allowlist[j] === u.origin || allowlist[j] === p.url) ok = true;
        }
        if (!ok) throw new Error("allowlist");
      }
      out.push({
        id: p.id,
        name: String(p.name||"").replace(/<[^>]*>/g,""),
        shortDescription: String(p.shortDescription||"").replace(/<[^>]*>/g,""),
        tooltip: String(p.tooltip||"").replace(/<[^>]*>/g,""),
        url: p.url,
        icon: p.icon,
        accentColor: p.accentColor || null,
        accentSoft: p.accentSoft || null,
        markInitial: p.markInitial || null,
        status: p.status,
        order: p.order,
        visibleInLauncher: p.visibleInLauncher !== false
      });
    }
    for (var k = 0; k < ALLOWED.length; k++) if (!seen[ALLOWED[k]]) throw new Error("missing");
    out.sort(function(a,b){ return a.order - b.order; });
    return out;
  }

  function clickable(p) {
    if (p.status === "coming_soon" || p.status === "unavailable") return false;
    return typeof p.url === "string" && p.url.indexOf("https://") === 0;
  }

  function deviceClass() {
    try { return window.matchMedia("(max-width:640px)").matches ? "mobile" : "desktop"; }
    catch(e) { return "unknown"; }
  }

  function emit(name, meta) {
    try {
      var detail = Object.assign({ launcherVersion: LAUNCHER_VERSION }, meta || {});
      window.dispatchEvent(new CustomEvent(name, { detail: detail, bubbles: true }));
      if (typeof window.gtag === "function") window.gtag("event", name, detail);
    } catch (e) {}
  }

  var ICONS = {"flows":"<svg viewBox=\"0 0 24 24\" width=\"24\" height=\"24\" fill=\"none\" aria-hidden=\"true\"><rect x=\"1\" y=\"1\" width=\"22\" height=\"22\" rx=\"6\" fill=\"#1a1f28\"/><path d=\"M6 18 C6 13.5 10 14.5 12 11 C13.2 8.8 16 8 18 7.4\" stroke=\"#1f6bb5\" stroke-width=\"1.7\" stroke-linecap=\"round\" stroke-dasharray=\"0.8 3.2\"/><circle cx=\"6\" cy=\"18\" r=\"1.85\" fill=\"#1f6bb5\"/><circle cx=\"18\" cy=\"7.2\" r=\"2.1\" fill=\"none\" stroke=\"#1f6bb5\" stroke-width=\"1.5\"/></svg>","oort":"<svg viewBox=\"0 0 24 24\" width=\"24\" height=\"24\" fill=\"none\" aria-hidden=\"true\"><rect x=\"1\" y=\"1\" width=\"22\" height=\"22\" rx=\"6\" fill=\"#0f172a\"/><ellipse cx=\"12\" cy=\"12.5\" rx=\"8\" ry=\"5.2\" transform=\"rotate(-28 12 12.5)\" stroke=\"#f97316\" stroke-width=\"1.4\" opacity=\"0.85\"/><ellipse cx=\"12\" cy=\"12.5\" rx=\"8\" ry=\"5.2\" transform=\"rotate(48 12 12.5)\" stroke=\"#fb923c\" stroke-width=\"1.2\" opacity=\"0.7\"/><circle cx=\"12\" cy=\"12.5\" r=\"2.4\" fill=\"#f97316\"/><circle cx=\"7.2\" cy=\"9.2\" r=\"0.7\" fill=\"#fdba74\"/><circle cx=\"17\" cy=\"11\" r=\"0.65\" fill=\"#fed7aa\"/></svg>","qev":"<svg viewBox=\"0 0 24 24\" width=\"24\" height=\"24\" fill=\"none\" aria-hidden=\"true\"><rect x=\"1\" y=\"1\" width=\"22\" height=\"22\" rx=\"6\" fill=\"#042f2e\"/><path d=\"M12 4.2l6.2 2.2v4.6c0 3.9-2.6 6.7-6.2 8.2-3.6-1.5-6.2-4.3-6.2-8.2V6.4L12 4.2z\" fill=\"#0f766e\"/><path d=\"M12 4.2l6.2 2.2v4.6c0 3.9-2.6 6.7-6.2 8.2-3.6-1.5-6.2-4.3-6.2-8.2V6.4L12 4.2z\" stroke=\"#5eead4\" stroke-width=\"1.1\" opacity=\"0.55\"/><path d=\"M9.1 12.1l2 2 3.9-4.4\" stroke=\"#ecfdf5\" stroke-width=\"1.7\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg>","lolm":"<svg viewBox=\"0 0 24 24\" width=\"24\" height=\"24\" fill=\"none\" aria-hidden=\"true\"><rect x=\"1\" y=\"1\" width=\"22\" height=\"22\" rx=\"6\" fill=\"#07090d\"/><path d=\"M4 6.2 Q12.5 6.2 17.2 12\" stroke=\"#4ea1ff\" stroke-width=\"1.55\" fill=\"none\" stroke-linecap=\"round\"/><path d=\"M4 9.2 Q12 9.2 17.2 12\" stroke=\"#b07fff\" stroke-width=\"1.55\" fill=\"none\" stroke-linecap=\"round\"/><path d=\"M4 12 H17.2\" stroke=\"#ffb454\" stroke-width=\"1.55\" stroke-linecap=\"round\"/><path d=\"M4 14.8 Q12 14.8 17.2 12\" stroke=\"#3fd6a0\" stroke-width=\"1.55\" fill=\"none\" stroke-linecap=\"round\"/><path d=\"M4 17.8 Q12.5 17.8 17.2 12\" stroke=\"#ff6b81\" stroke-width=\"1.55\" fill=\"none\" stroke-linecap=\"round\"/><circle cx=\"17.2\" cy=\"12\" r=\"1.85\" fill=\"#d7dde6\"/></svg>","ledger":"<svg viewBox=\"0 0 24 24\" width=\"24\" height=\"24\" fill=\"none\" aria-hidden=\"true\"><rect x=\"1\" y=\"1\" width=\"22\" height=\"22\" rx=\"6\" fill=\"#0d1220\"/><rect x=\"4.2\" y=\"6.2\" width=\"7.2\" height=\"1.7\" rx=\"0.85\" fill=\"#8593ad\"/><rect x=\"4.2\" y=\"10.2\" width=\"4.6\" height=\"1.7\" rx=\"0.85\" fill=\"#66738d\"/><rect x=\"4.2\" y=\"14.2\" width=\"6\" height=\"1.7\" rx=\"0.85\" fill=\"#4d5a73\"/><path d=\"M16.8 6.4 L19.6 8.8 L12.2 17.8 L7.4 13 L10 10.5 L11.9 12.4 Z\" fill=\"#0d1220\"/><path d=\"M17.3 7 L19 8.5 L12.1 16.8 L8.4 13.1 L10 11.5 L11.9 13.5 Z\" fill=\"#22c55e\"/></svg>","aex":"<svg viewBox=\"0 0 24 24\" width=\"24\" height=\"24\" fill=\"none\" aria-hidden=\"true\"><rect x=\"1.2\" y=\"1.2\" width=\"21.6\" height=\"21.6\" rx=\"5\" fill=\"#070b12\" stroke=\"#00e8c0\" stroke-width=\"1.2\"/><path d=\"M7.2 17 L12 6.2 L16.8 17\" stroke=\"#f0f4fa\" stroke-width=\"1.7\" stroke-linejoin=\"miter\" stroke-linecap=\"square\"/><path d=\"M9.2 13.2 H14.8\" stroke=\"#00e8c0\" stroke-width=\"1.55\" stroke-linecap=\"square\"/><path d=\"M6.6 18.6 H17.4\" stroke=\"#00e8c0\" stroke-width=\"1\" stroke-linecap=\"square\" opacity=\"0.55\"/></svg>"};

  function gridIcon() {
    return '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor" aria-hidden="true"><circle cx="3" cy="3" r="1.6"/><circle cx="9" cy="3" r="1.6"/><circle cx="15" cy="3" r="1.6"/><circle cx="3" cy="9" r="1.6"/><circle cx="9" cy="9" r="1.6"/><circle cx="15" cy="9" r="1.6"/><circle cx="3" cy="15" r="1.6"/><circle cx="9" cy="15" r="1.6"/><circle cx="15" cy="15" r="1.6"/></svg>';
  }

  function resolveTheme(attr) {
    if (attr === "dark" || attr === "light") return attr;
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    } catch (e) { return "light"; }
  }

  class QiraProductLauncher extends HTMLElement {
    constructor() {
      super();
      this._open = false;
      this._root = this.attachShadow({ mode: "open" });
      this._products = null;
      this._portalHost = null;
      this._panelId = "qira-apps-panel-" + Math.random().toString(36).slice(2, 9);
      this._onDoc = this._onDoc.bind(this);
      this._onKey = this._onKey.bind(this);
      this._onReposition = this._onReposition.bind(this);
    }

    static get observedAttributes() {
      return ["current-product", "theme"];
    }

    connectedCallback() {
      try {
        this._products = sanitize(BUNDLED.products, BUNDLED.allowlist);
      } catch (e) {
        console.error("[qira-product-launcher] registry failed", e);
        this._products = [];
      }
      this._render();
    }

    disconnectedCallback() {
      document.removeEventListener("mousedown", this._onDoc);
      document.removeEventListener("keydown", this._onKey);
      window.removeEventListener("resize", this._onReposition);
      window.removeEventListener("scroll", this._onReposition, true);
      document.body.style.overflow = this._prevOverflow || "";
      this._hideTip();
      this._unmountPortal();
    }

    attributeChangedCallback() {
      if (this.isConnected) this._render();
    }

    get currentProduct() {
      var v = this.getAttribute("current-product");
      return isAllowed(v) ? v : null;
    }

    _render() {
      var theme = resolveTheme(this.getAttribute("theme") || "auto");
      var html = "";
      html += "<style>" + STYLES + "</style>";
      html += '<div class="qira-launcher" data-theme="' + theme + '" data-qira-launcher="">';
      html += '<button type="button" class="qira-launcher__trigger" aria-label="Open Qira Apps" aria-expanded="' +
        (this._open ? "true" : "false") + '" aria-controls="' + this._panelId + '" aria-haspopup="dialog" part="trigger">' +
        gridIcon() + "</button>";
      html += "</div>";
      this._root.innerHTML = html;
      var self = this;
      var trigger = this._root.querySelector(".qira-launcher__trigger");
      if (trigger) {
        trigger.addEventListener("click", function (e) {
          e.stopPropagation();
          self._toggle();
        });
      }
      if (this._open) this._mountPortal();
      else this._unmountPortal();
    }

    _panelMarkup(theme, current, products) {
      var html = "";
      html += "<style>" + STYLES + "</style>";
      html += '<div class="qira-launcher qira-launcher--portal" data-theme="' + theme + '" data-open="true" data-qira-launcher="">';
      html += '<button type="button" class="qira-launcher__scrim" aria-label="Close Qira Apps" tabindex="-1" data-close></button>';
      html += '<div id="' + this._panelId + '" class="qira-launcher__panel" role="dialog" aria-modal="true" aria-label="Qira Apps" data-qira-panel part="panel">';
      html += '<div class="qira-launcher__header"><h2 class="qira-launcher__title">Qira Apps</h2>';
      html += '<button type="button" class="qira-launcher__close" aria-label="Close Qira Apps" data-close>';
      html += '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke-linecap="round"/></svg>';
      html += "</button></div>";
      html += '<div class="qira-launcher__grid" data-qira-grid="">';
      for (var i = 0; i < products.length; i++) {
        html += this._tile(products[i], current);
      }
      html += "</div></div></div>";
      return html;
    }

    _mountPortal() {
      this._unmountPortal();
      var theme = resolveTheme(this.getAttribute("theme") || "auto");
      var current = this.currentProduct;
      var products = this._products || [];
      var host = document.createElement("div");
      host.setAttribute("data-qira-apps-portal", "");
      // Fixed full-viewport host escapes sticky / backdrop-filter containing blocks in nav bars
      host.style.cssText = "position:fixed;inset:0;width:100%;height:100%;z-index:2147483000;pointer-events:none;";
      var shadow = host.attachShadow({ mode: "open" });
      shadow.innerHTML = this._panelMarkup(theme, current, products);
      document.body.appendChild(host);
      this._portalHost = host;
      this._wirePortal(shadow, current);
      this._positionPortalPanel();
      window.addEventListener("resize", this._onReposition);
      window.addEventListener("scroll", this._onReposition, true);
    }

    _unmountPortal() {
      window.removeEventListener("resize", this._onReposition);
      window.removeEventListener("scroll", this._onReposition, true);
      if (this._portalHost && this._portalHost.parentNode) {
        this._portalHost.parentNode.removeChild(this._portalHost);
      }
      this._portalHost = null;
    }

    _wirePortal(shadow, current) {
      var self = this;
      shadow.querySelectorAll("[data-close]").forEach(function (el) {
        el.addEventListener("click", function () { self._close(); });
      });
      shadow.querySelectorAll("[data-product-id]").forEach(function (el) {
        el.addEventListener("click", function (ev) {
          if (el.getAttribute("data-disabled") === "true") {
            ev.preventDefault();
            return;
          }
          var id = el.getAttribute("data-product-id");
          emit("qira_product_selected", {
            currentProductId: current,
            destinationProductId: id,
            deviceClass: deviceClass(),
          });
        });
        var tip = el.getAttribute("data-tooltip");
        if (tip) {
          el.addEventListener("mouseenter", function () { self._showTip(el, tip); });
          el.addEventListener("mouseleave", function () { self._hideTip(); });
          el.addEventListener("focus", function () { self._showTip(el, tip); });
          el.addEventListener("blur", function () { self._hideTip(); });
        }
      });
    }

    _positionPortalPanel() {
      if (!this._portalHost || !this._portalHost.shadowRoot) return;
      var panel = this._portalHost.shadowRoot.querySelector(".qira-launcher__panel");
      if (!panel) return;
      var mobile = false;
      try { mobile = window.matchMedia("(max-width:640px)").matches; } catch (e) {}
      if (mobile) {
        panel.style.position = "fixed";
        panel.style.left = "0.75rem";
        panel.style.right = "0.75rem";
        panel.style.top = "auto";
        panel.style.bottom = "max(0.75rem, env(safe-area-inset-bottom, 0px))";
        panel.style.width = "auto";
        panel.style.maxWidth = "none";
        panel.style.pointerEvents = "auto";
        return;
      }
      var trigger = this._root.querySelector(".qira-launcher__trigger") || this;
      var r = trigger.getBoundingClientRect();
      var width = Math.min(window.innerWidth - 24, 20.5 * 16);
      var top = r.bottom + 8;
      var left = Math.min(Math.max(8, r.right - width), window.innerWidth - width - 8);
      panel.style.position = "fixed";
      panel.style.top = top + "px";
      panel.style.left = left + "px";
      panel.style.right = "auto";
      panel.style.bottom = "auto";
      panel.style.width = width + "px";
      panel.style.maxWidth = "calc(100vw - 1.5rem)";
      panel.style.zIndex = "2147483001";
      panel.style.pointerEvents = "auto";
    }

    _onReposition() {
      if (this._open) this._positionPortalPanel();
    }

    _tile(p, current) {
      var isCurrent = current && p.id === current;
      var disabled = !clickable(p);
      var badge = "";
      if (isCurrent) badge = '<span class="qira-launcher__badge qira-launcher__badge--here">Here</span>';
      else if (p.status === "coming_soon") badge = '<span class="qira-launcher__badge qira-launcher__badge--soon" aria-label="' + p.name + ' Coming Soon">Coming Soon</span>';
      else if (p.status === "research") badge = '<span class="qira-launcher__badge qira-launcher__badge--research">Research</span>';
      var desc = disabled && p.status === "coming_soon" ? "Coming Soon" : p.shortDescription;
      var icon = ICONS[p.id] || "";
      var cls = "qira-launcher__tile" + (isCurrent ? " qira-launcher__tile--current" : "") + (disabled ? " qira-launcher__tile--disabled" : "");
      var iconStyle = "";
      if (p.accentSoft || p.accentColor) {
        iconStyle = ' style="--ql-product-soft:' + (p.accentSoft || p.accentColor) +
          ";--ql-product-accent:" + (p.accentColor || "#5f6368") + ';"';
      }
      var body = '<div class="qira-launcher__tile-top"><span class="qira-launcher__icon" data-product-id="' + p.id + '" aria-hidden="true"' + iconStyle + ">" + icon + "</span>" + badge + "</div>";
      body += '<p class="qira-launcher__name">' + p.name + "</p>";
      body += '<p class="qira-launcher__desc">' + desc + "</p>";
      if (disabled) {
        return '<div class="' + cls + '" role="link" aria-disabled="true" aria-label="' + p.name + ', Coming Soon" data-product-id="' + p.id + '" data-disabled="true" data-tooltip="' + p.tooltip.replace(/"/g, "&quot;") + '" tabindex="0">' + body + "</div>";
      }
      if (isCurrent || !p.url) {
        return '<div class="' + cls + '" role="link" aria-current="page" aria-label="' + p.name + ', current app" data-product-id="' + p.id + '" data-current="true" data-tooltip="' + p.tooltip.replace(/"/g, "&quot;") + '" tabindex="0">' + body + "</div>";
      }
      return '<a class="' + cls + '" href="' + p.url + '" data-product-id="' + p.id + '" data-tooltip="' + p.tooltip.replace(/"/g, "&quot;") + '">' + body + "</a>";
    }

    _showTip(el, text) {
      // Body-portal tip: white panel, dark text, not clipped by launcher panel
      this._hideTip();
      var host = document.createElement("div");
      host.setAttribute("data-qira-apps-tip", "");
      host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483646;";
      var shadow = host.attachShadow({ mode: "open" });
      var style = document.createElement("style");
      style.textContent =
        ".tip{position:fixed;z-index:1;max-width:min(17.5rem,calc(100vw - 1rem));padding:0.5rem 0.65rem;border-radius:0.5rem;border:1px solid rgba(60,64,67,0.18);background:#ffffff;color:#202124;font:500 0.8125rem/1.4 Inter,system-ui,sans-serif;box-shadow:0 1px 2px rgba(60,64,67,0.15),0 2px 6px 2px rgba(60,64,67,0.1);white-space:normal;overflow-wrap:anywhere;pointer-events:none;}";
      var t = document.createElement("div");
      t.className = "tip";
      t.setAttribute("role", "tooltip");
      t.textContent = text;
      shadow.appendChild(style);
      shadow.appendChild(t);
      document.body.appendChild(host);
      this._tipHost = host;
      var r = el.getBoundingClientRect();
      var tw = Math.min(280, window.innerWidth - 16);
      t.style.width = "max-content";
      t.style.maxWidth = tw + "px";
      // Prefer below tile; flip above if near bottom
      var top = r.bottom + 8;
      var left = Math.max(8, Math.min(window.innerWidth - tw - 8, r.left + r.width / 2 - tw / 2));
      requestAnimationFrame(function () {
        var h = t.offsetHeight || 48;
        var w = t.offsetWidth || tw;
        if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
        left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2));
        t.style.left = left + "px";
        t.style.top = top + "px";
      });
    }

    _hideTip() {
      if (this._tipHost && this._tipHost.parentNode) this._tipHost.parentNode.removeChild(this._tipHost);
      this._tipHost = null;
      if (this._tip && this._tip.parentNode) this._tip.parentNode.removeChild(this._tip);
      this._tip = null;
    }

    _toggle() {
      if (this._open) this._close();
      else this._openPanel();
    }

    _openPanel() {
      this._open = true;
      this._render();
      emit("qira_launcher_opened", {
        currentProductId: this.currentProduct,
        deviceClass: deviceClass(),
      });
      document.addEventListener("mousedown", this._onDoc);
      document.addEventListener("keydown", this._onKey);
      try {
        if (window.matchMedia("(max-width:640px)").matches) {
          this._prevOverflow = document.body.style.overflow;
          document.body.style.overflow = "hidden";
        }
      } catch (e) {}
      var t = this._root.querySelector(".qira-launcher__trigger");
      if (t) t.focus();
    }

    _close() {
      if (!this._open) return;
      this._open = false;
      this._hideTip();
      document.removeEventListener("mousedown", this._onDoc);
      document.removeEventListener("keydown", this._onKey);
      document.body.style.overflow = this._prevOverflow || "";
      this._unmountPortal();
      this._render();
      emit("qira_launcher_closed", {
        currentProductId: this.currentProduct,
        deviceClass: deviceClass(),
      });
      var t = this._root.querySelector(".qira-launcher__trigger");
      if (t) t.focus();
    }

    _onDoc(e) {
      var path = e.composedPath ? e.composedPath() : [];
      if (path.indexOf(this) !== -1) return;
      if (this._portalHost && path.indexOf(this._portalHost) !== -1) return;
      // mobile scrim handles close
      try {
        if (window.matchMedia("(max-width:640px)").matches) return;
      } catch (err) {}
      this._close();
    }

    _onKey(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        this._close();
      }
    }
  }

  customElements.define("qira-product-launcher", QiraProductLauncher);
})();
