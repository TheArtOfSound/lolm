/**
 * LOLM public product configuration loader.
 * Canonical static source: /product-config.json
 * Optional live overlay: GET /api/demo/billing/config (tiers only; no secrets)
 *
 * Pages may call:
 *   const cfg = await LOLMProduct.load();
 *   LOLMProduct.formatUsd(7.99) -> "$7.99"
 *   LOLMProduct.renderPlanLine(cfg.plans.plus) -> "Plus · $7.99 · 300 runs/day"
 */
(function (global) {
  "use strict";

  const STATIC_URL = "/product-config.json";
  const BILLING_URL = "/api/demo/billing/config";
  let _cache = null;

  function formatUsd(n) {
    const x = Number(n);
    if (!isFinite(x)) return "";
    if (x === 0) return "$0";
    return Number.isInteger(x) ? "$" + x : "$" + x.toFixed(2);
  }

  function renderPlanLine(plan) {
    if (!plan) return "";
    return (
      plan.label +
      " · " +
      formatUsd(plan.usd) +
      (plan.usd > 0 ? "/mo" : "") +
      " · " +
      plan.runs_per_day +
      " runs/day · " +
      plan.visual_per_day +
      " visual builds/day"
    );
  }

  function mergeBillingTiers(cfg, billing) {
    if (!cfg || !billing || !billing.tiers) return cfg;
    const out = JSON.parse(JSON.stringify(cfg));
    out.plans = out.plans || {};
    for (const [id, t] of Object.entries(billing.tiers)) {
      out.plans[id] = Object.assign({}, out.plans[id] || {}, {
        id: id,
        label: t.label || (out.plans[id] && out.plans[id].label) || id,
        usd: t.usd,
        runs_per_day: t.runs_per_day,
        visual_per_day: t.visual_per_day,
      });
    }
    out._billingLive = true;
    out._yourTier = billing;
    return out;
  }

  async function load(opts) {
    opts = opts || {};
    if (_cache && !opts.force) return _cache;
    let cfg;
    try {
      const r = await fetch(STATIC_URL, { cache: "no-store" });
      if (!r.ok) throw new Error("product-config " + r.status);
      cfg = await r.json();
    } catch (e) {
      // Fallback matching usage_limits.TIERS — never invent $9/$19 marketing numbers
      cfg = {
        version: 0,
        product: {
          name: "LOLM",
          tagline: "An agent that does not lose the plot.",
          publisher: "Qira LLC",
        },
        plans: {
          free: { id: "free", label: "Free", usd: 0, runs_per_day: 10, visual_per_day: 3 },
          plus: { id: "plus", label: "Plus", usd: 7.99, runs_per_day: 300, visual_per_day: 30 },
          pro: { id: "pro", label: "Pro", usd: 19.99, runs_per_day: 2000, visual_per_day: 200 },
        },
        billing: { topups: { available: false } },
      };
    }
    if (opts.liveBilling !== false) {
      try {
        const br = await fetch(BILLING_URL, { cache: "no-store" });
        if (br.ok) {
          const billing = await br.json();
          cfg = mergeBillingTiers(cfg, billing);
        }
      } catch (_) {
        /* static plans remain authoritative for display */
      }
    }
    _cache = cfg;
    return cfg;
  }

  /** Safe text set — never assign untrusted HTML. */
  function setText(el, text) {
    if (!el) return;
    el.textContent = text == null ? "" : String(text);
  }

  /** Append a text node + optional safe link children without innerHTML. */
  function clear(el) {
    if (!el) return;
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function appendText(el, text) {
    el.appendChild(document.createTextNode(text == null ? "" : String(text)));
  }

  function appendLink(el, href, label, className) {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = label;
    if (className) a.className = className;
    el.appendChild(a);
    return a;
  }

  global.LOLMProduct = {
    load: load,
    formatUsd: formatUsd,
    renderPlanLine: renderPlanLine,
    setText: setText,
    clear: clear,
    appendText: appendText,
    appendLink: appendLink,
    STATIC_URL: STATIC_URL,
  };
})(typeof window !== "undefined" ? window : globalThis);
