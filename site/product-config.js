(function (global) {
  "use strict";
  var cached = null;
  async function load() {
    if (cached) return cached;
    var response = await fetch("/product-config.json", { cache: "no-store" });
    if (!response.ok) throw new Error("product-config " + response.status);
    cached = await response.json();
    return cached;
  }
  global.LOLMProduct = { load: load, STATIC_URL: "/product-config.json" };
})(typeof window !== "undefined" ? window : globalThis);
