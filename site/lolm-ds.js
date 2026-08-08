/* Copyright (c) 2026 Qira LLC. All rights reserved.
 * LOLM design system — theme persistence, toggle, and Qira Apps launcher.
 *
 * Deliberately tiny, dependency-free, and safe to run before the rest of the page:
 * the stylesheet already themes off prefers-color-scheme, so this only has to
 * handle an explicit override and remember it. No external requests, so the
 * offline-first service worker keeps working.
 */
(function () {
  "use strict";

  var KEY = "lolm-theme";          // "dark" | "light" | absent = follow the OS
  var LAUNCHER_SRC = "https://imagineqira.com/assets/qira-apps/qira-product-launcher.js?v=20260807portal";
  var root = document.documentElement;

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function systemDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function effective() {
    var s = stored();
    if (s === "dark" || s === "light") return s;
    var pageDefault = root.getAttribute("data-default-theme");
    if (pageDefault === "dark" || pageDefault === "light") return pageDefault;
    // The stylesheet's :root default is dark, and light only applies under the
    // prefers-color-scheme:light query — so "no preference" resolves to dark too.
    return systemDark() ? "dark" : "light";
  }

  function apply(theme, persist) {
    if (theme) root.setAttribute("data-theme", theme);
    else {
      var pageDefault = root.getAttribute("data-default-theme");
      if (pageDefault === "dark" || pageDefault === "light") root.setAttribute("data-theme", pageDefault);
      else root.removeAttribute("data-theme");
    }
    if (persist) {
      try {
        if (theme) localStorage.setItem(KEY, theme);
        else localStorage.removeItem(KEY);
      } catch (e) { /* private mode — the attribute still holds for this page */ }
    }
    // Keep the mobile browser chrome in step with the page.
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", effective() === "dark" ? "#07080b" : "#fcfcfd");
    var btn = document.querySelector(".lolm-theme-toggle");
    if (btn) {
      var dark = effective() === "dark";
      btn.textContent = dark ? "☀" : "☾";
      btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      btn.setAttribute("title", btn.getAttribute("aria-label"));
    }
    document.querySelectorAll("qira-product-launcher").forEach(function (launcher) {
      launcher.setAttribute("theme", effective());
    });
  }

  // Apply the stored choice before first paint where possible (this script is
  // loaded in <head>), so a light-theme user never sees a dark flash.
  var initial = stored();
  if (initial === "dark" || initial === "light") apply(initial, false);

  function mount() {
    if (!document.querySelector(".lolm-theme-toggle")) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "lolm-theme-toggle";
      btn.addEventListener("click", function () {
        apply(effective() === "dark" ? "light" : "dark", true);
      });
      document.body.appendChild(btn);
      apply(stored(), false);
    }
    mountQiraLauncher();
  }

  function launcherTarget() {
    return document.querySelector("header nav") ||
      document.querySelector("header") ||
      document.querySelector("main.shell > nav, .shell > nav");
  }

  function mountQiraLauncher() {
    if (document.querySelector("qira-product-launcher")) return;

    var slot = document.createElement("span");
    slot.className = "lolm-qira-apps-slot";
    slot.setAttribute("aria-label", "Qira Apps");

    var target = launcherTarget();
    if (target) {
      var isHeaderNav = Boolean(target.closest("header"));
      if (!isHeaderNav && target.lastElementChild) {
        slot.classList.add("lolm-qira-apps-slot--end-group");
        target.insertBefore(slot, target.lastElementChild);
      } else {
        target.appendChild(slot);
      }
    } else {
      slot.classList.add("lolm-qira-apps-slot--floating");
      document.body.appendChild(slot);
    }

    function renderLauncher() {
      if (!customElements.get("qira-product-launcher")) return;
      var launcher = document.createElement("qira-product-launcher");
      launcher.setAttribute("current-product", "lolm");
      launcher.setAttribute("theme", effective());
      slot.replaceChildren(launcher);
    }

    if (customElements.get("qira-product-launcher")) {
      renderLauncher();
      return;
    }

    var script = document.querySelector('script[data-qira-product-launcher]');
    if (!script) {
      script = document.createElement("script");
      script.src = LAUNCHER_SRC;
      script.async = true;
      script.dataset.qiraProductLauncher = "";
      script.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
      document.head.appendChild(script);
    }
    script.addEventListener("load", renderLauncher, { once: true });
    script.addEventListener("error", function () {
      // Progressive enhancement: keep LOLM navigation usable if the shared
      // ecosystem asset is temporarily unavailable.
      slot.remove();
    }, { once: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  // Follow the OS live, but only while the user has expressed no preference.
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function () { if (!stored()) apply(null, false); };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }
})();
