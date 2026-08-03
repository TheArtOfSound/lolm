/* Copyright (c) 2026 Qira LLC. All rights reserved.
 * Live artifact delivery for the LOLM workspace.
 * Intercepts a tee of the code SSE stream without changing the app's own reader.
 */
(function () {
  "use strict";
  if (window.__lolmArtifactDeliveryInstalled) return;
  window.__lolmArtifactDeliveryInstalled = true;

  var originalFetch = window.fetch.bind(window);
  var current = { manifest: null, receipt: null, urls: [] };

  function clearUrls() {
    current.urls.forEach(function (url) { try { URL.revokeObjectURL(url); } catch (_) {} });
    current.urls = [];
  }

  function bytesFor(file) {
    if (file.encoding === "base64" && typeof file.content_base64 === "string") {
      var raw = atob(file.content_base64);
      var out = new Uint8Array(raw.length);
      for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
      return out;
    }
    if ((file.encoding === "utf-8" || file.encoding === "utf8") && typeof file.content === "string") {
      return new TextEncoder().encode(file.content);
    }
    return null;
  }

  function mimeFor(path) {
    var p = String(path || "").toLowerCase();
    if (p.endsWith(".pdf")) return "application/pdf";
    if (p.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    if (p.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    if (p.endsWith(".pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
    if (p.endsWith(".html") || p.endsWith(".htm")) return "text/html;charset=utf-8";
    if (p.endsWith(".png")) return "image/png";
    if (p.endsWith(".jpg") || p.endsWith(".jpeg")) return "image/jpeg";
    if (p.endsWith(".svg")) return "image/svg+xml";
    if (p.endsWith(".json")) return "application/json";
    if (p.endsWith(".csv")) return "text/csv;charset=utf-8";
    if (p.endsWith(".txt") || p.endsWith(".md")) return "text/plain;charset=utf-8";
    return "application/octet-stream";
  }

  function isUserArtifact(path) {
    return /\.(pdf|docx?|odt|rtf|txt|md|html?|png|jpe?g|svg|csv|xlsx|pptx|zip)$/i.test(String(path || ""));
  }

  function ensureHost() {
    var host = document.getElementById("lolm-artifact-delivery");
    if (host) return host;
    host = document.createElement("section");
    host.id = "lolm-artifact-delivery";
    host.setAttribute("aria-live", "polite");
    host.style.cssText = [
      "position:fixed", "right:18px", "bottom:18px", "z-index:120",
      "width:min(420px,calc(100vw - 32px))", "max-height:70vh", "overflow:auto",
      "background:var(--panel,#fff)", "color:var(--ink,#111)",
      "border:1px solid var(--line,#d9dee7)", "border-radius:16px",
      "box-shadow:0 18px 60px rgba(2,6,23,.22)", "padding:14px"
    ].join(";");
    document.body.appendChild(host);
    return host;
  }

  function addText(parent, tag, text, css) {
    var el = document.createElement(tag);
    el.textContent = text;
    if (css) el.style.cssText = css;
    parent.appendChild(el);
    return el;
  }

  function render() {
    if (!current.manifest) return;
    clearUrls();
    var host = ensureHost();
    host.replaceChildren();
    var receipt = current.receipt || {};
    var verification = receipt.verification || {};
    var bound = Boolean(
      receipt.ok === true &&
      verification.artifact_manifest_ok === true &&
      verification.artifact_manifest_sha256 &&
      verification.artifact_manifest_sha256 === current.manifest.manifest_sha256
    );

    var head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:center;gap:10px;margin-bottom:10px";
    addText(head, "strong", "Generated artifacts", "font-size:14px;flex:1");
    addText(
      head,
      "span",
      bound ? "verified" : (receipt.verdict ? "not delivered" : "verifying"),
      "font:11px ui-monospace,monospace;padding:3px 7px;border-radius:999px;background:" +
        (bound ? "#dcfce7;color:#166534" : "#fef3c7;color:#92400e")
    );
    var close = document.createElement("button");
    close.type = "button";
    close.textContent = "×";
    close.setAttribute("aria-label", "Close artifact panel");
    close.style.cssText = "border:0;background:transparent;font-size:22px;color:inherit";
    close.addEventListener("click", function () { host.remove(); });
    head.appendChild(close);
    host.appendChild(head);

    var files = (current.manifest.files || []).filter(function (file) {
      return file && file.type === "file" && isUserArtifact(file.path);
    });
    if (!files.length) {
      addText(host, "p", "No user-facing file was delivered. Source code may have run, but the requested artifact was not exported.", "font-size:13px;line-height:1.5;margin:0");
      return;
    }

    files.forEach(function (file) {
      var row = document.createElement("div");
      row.style.cssText = "border:1px solid var(--line,#d9dee7);border-radius:12px;padding:10px;margin-top:8px";
      addText(row, "div", file.path, "font-weight:650;font-size:13px;word-break:break-word");
      addText(row, "div", String(file.size || 0) + " bytes · sha256 " + String(file.sha256 || "").slice(0, 12), "font:10px ui-monospace,monospace;opacity:.65;margin:4px 0 8px");
      var body = bytesFor(file);
      if (!body) {
        addText(row, "div", "Artifact body was omitted, so this file cannot be downloaded from this run.", "font-size:12px;color:#b45309");
      } else {
        var url = URL.createObjectURL(new Blob([body], { type: mimeFor(file.path) }));
        current.urls.push(url);
        var a = document.createElement("a");
        a.href = url;
        a.download = String(file.path || "artifact").split("/").pop();
        a.textContent = bound ? "Download verified file" : "Download generated file";
        a.style.cssText = "display:inline-block;padding:8px 11px;border-radius:9px;background:#0a0c10;color:#fff;text-decoration:none;font-size:12px;font-weight:650";
        row.appendChild(a);
      }
      host.appendChild(row);
    });

    if (!bound && receipt.verdict) {
      addText(host, "p", "LOLM generated files, but the signed receipt did not authorize a shipped/delivered claim.", "font-size:12px;line-height:1.45;color:#92400e;margin:10px 0 0");
    }
  }

  function handleEvent(name, data) {
    if (name === "code_start") {
      clearUrls();
      current = { manifest: null, receipt: null, urls: [] };
      var old = document.getElementById("lolm-artifact-delivery");
      if (old) old.remove();
    } else if (name === "artifact_manifest") {
      current.manifest = data;
      render();
      window.dispatchEvent(new CustomEvent("lolm:artifact-manifest", { detail: data }));
    } else if (name === "code_receipt") {
      current.receipt = data;
      render();
      window.dispatchEvent(new CustomEvent("lolm:artifact-receipt", { detail: data }));
    }
  }

  async function inspectStream(stream) {
    var reader = stream.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    try {
      while (true) {
        var part = await reader.read();
        if (part.done) break;
        buffer += decoder.decode(part.value, { stream: true });
        var blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        blocks.forEach(function (block) {
          var event = "message";
          var dataLines = [];
          block.split(/\r?\n/).forEach(function (line) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
          });
          if (!dataLines.length) return;
          try { handleEvent(event, JSON.parse(dataLines.join("\n"))); } catch (_) {}
        });
      }
    } catch (_) {
      // The app's primary stream remains authoritative; this observer is optional.
    } finally {
      try { reader.releaseLock(); } catch (_) {}
    }
  }

  window.fetch = async function (input, init) {
    var response = await originalFetch(input, init);
    try {
      var raw = typeof input === "string" ? input : (input && input.url) || "";
      var url = new URL(raw, location.href);
      if (url.pathname === "/api/demo/code/run" && response.body) {
        var branches = response.body.tee();
        inspectStream(branches[1]);
        return new Response(branches[0], {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      }
    } catch (_) {}
    return response;
  };
})();
