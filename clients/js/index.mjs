/**
 * lolm-nfet-client — client for the LOLM-NFET agent protocol.
 *
 * The LOLM-NFET agent (https://lolm.imagineqira.com) streams its runs as
 * Server-Sent Events: segments of draft text, control decisions made from
 * the model's own latent telemetry (entropy, drift, gate, regime), the
 * actions those decisions trigger, and a proof receipt comparing the result
 * against base mode. This package speaks that protocol from Node (>=18) or
 * the browser: live runs, recorded-replay playback, and a plain-English
 * narration helper.
 *
 * Zero dependencies. MIT licensed (the client; the model is separately
 * licensed under the LOLM Community License).
 */

/** Error thrown when a run cannot start or the stream reports an error. */
export class AgentRunError extends Error {
  constructor(message, { status = null, body = null, code = "AGENT_RUN_ERROR", cause = null } = {}) {
    super(message);
    this.name = "AgentRunError";
    this.status = status;
    this.body = body;
    this.code = code;
    if (cause) this.cause = cause;
  }
}

const DEFAULT_TIMEOUT_MS = 120_000;
const DEFAULT_IDLE_TIMEOUT_MS = 30_000;
const DEFAULT_JSON_BYTES = 5 * 1024 * 1024;
const DEFAULT_SSE_EVENT_BYTES = 2 * 1024 * 1024;
const DEFAULT_SSE_STREAM_BYTES = 32 * 1024 * 1024;

function networkScope({ signal: parentSignal, timeoutMs = DEFAULT_TIMEOUT_MS,
  idleTimeoutMs = 0 } = {}) {
  const controller = new AbortController();
  let reasonCode = null;
  let deadlineTimer = null;
  let idleTimer = null;
  const abort = (code, message) => {
    if (controller.signal.aborted) return;
    reasonCode = code;
    controller.abort(new DOMException(message, "AbortError"));
  };
  const onParentAbort = () => abort("CANCELLED", "request cancelled");
  if (parentSignal?.aborted) onParentAbort();
  else parentSignal?.addEventListener("abort", onParentAbort, { once: true });
  if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
    deadlineTimer = setTimeout(() => abort("TIMEOUT", "request timed out"), timeoutMs);
  }
  const touch = () => {
    if (!(Number.isFinite(idleTimeoutMs) && idleTimeoutMs > 0)) return;
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => abort("IDLE_TIMEOUT", "stream inactivity timeout"), idleTimeoutMs);
  };
  touch();
  return {
    signal: controller.signal,
    touch,
    cleanup() {
      if (deadlineTimer) clearTimeout(deadlineTimer);
      if (idleTimer) clearTimeout(idleTimer);
      parentSignal?.removeEventListener("abort", onParentAbort);
    },
    error(error) {
      if (error instanceof AgentRunError) return error;
      if (reasonCode) {
        const message = reasonCode === "TIMEOUT" ? "request timed out"
          : reasonCode === "IDLE_TIMEOUT" ? "stream inactivity timeout"
          : "request cancelled";
        return new AgentRunError(message, { code: reasonCode, cause: error });
      }
      return new AgentRunError(error?.message || String(error), {
        code: "NETWORK_ERROR", cause: error,
      });
    },
  };
}

async function readJsonResponse(response, maxBytes = DEFAULT_JSON_BYTES) {
  if (!response.body) {
    const text = await response.text();
    if (new TextEncoder().encode(text).byteLength > maxBytes) {
      throw new AgentRunError("JSON response exceeds size limit", { code: "RESPONSE_TOO_LARGE" });
    }
    return JSON.parse(text);
  }
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel("response too large");
        throw new AgentRunError("JSON response exceeds size limit", { code: "RESPONSE_TOO_LARGE" });
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder().decode(bytes));
}

/**
 * Parse a fetch-response body (ReadableStream) of Server-Sent Events into
 * `{event, data}` objects. `data:` payloads are JSON-parsed.
 */
export async function* parseSSEStream(stream, {
  maxEventBytes = DEFAULT_SSE_EVENT_BYTES,
  maxStreamBytes = DEFAULT_SSE_STREAM_BYTES,
  onActivity,
} = {}) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let streamBytes = 0;
  let eventName = "message";
  let dataLines = [];
  let eventBytes = 0;

  const parseData = (raw) => {
    try { return JSON.parse(raw); } catch { return raw; }
  };
  const dispatchEvent = () => {
    if (!dataLines.length) {
      eventName = "message";
      eventBytes = 0;
      return null;
    }
    const raw = dataLines.join("\n");
    const event = { event: eventName || "message", data: parseData(raw) };
    eventName = "message";
    dataLines = [];
    eventBytes = 0;
    return event;
  };
  const processLine = (line) => {
    if (line === "") return dispatchEvent();
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event" && !value.includes("\0")) eventName = value || "message";
    if (field === "data") {
      eventBytes += new TextEncoder().encode(value).byteLength;
      if (eventBytes > maxEventBytes) {
        throw new AgentRunError("SSE event exceeds size limit", { code: "SSE_EVENT_TOO_LARGE" });
      }
      dataLines.push(value);
    }
    return null;
  };
  const nextLine = (eof = false) => {
    for (let i = 0; i < buf.length; i++) {
      if (buf[i] === "\n") {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        return line;
      }
      if (buf[i] === "\r") {
        if (i + 1 === buf.length && !eof) return null;
        const width = buf[i + 1] === "\n" ? 2 : 1;
        const line = buf.slice(0, i);
        buf = buf.slice(i + width);
        return line;
      }
    }
    if (eof && buf.length) {
      const line = buf;
      buf = "";
      return line;
    }
    return null;
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      onActivity?.();
      streamBytes += value.byteLength;
      if (streamBytes > maxStreamBytes) {
        await reader.cancel("stream too large");
        throw new AgentRunError("SSE stream exceeds size limit", { code: "SSE_STREAM_TOO_LARGE" });
      }
      buf += decoder.decode(value, { stream: true });
      while (true) {
        const line = nextLine(false);
        if (line === null) break;
        const event = processLine(line);
        if (event) yield event;
      }
    }
    buf += decoder.decode();
    while (true) {
      const line = nextLine(true);
      if (line === null) break;
      const event = processLine(line);
      if (event) yield event;
    }
    const finalEvent = dispatchEvent();
    if (finalEvent) yield finalEvent;
  } finally {
    reader.releaseLock();
  }
}

function dispatch(ev, handlers) {
  const { onEvent, onToken, onDecision, onAction, onProof, onPhase } = handlers;
  if (onEvent) onEvent(ev);
  if (ev.event === "token" && onToken) onToken(ev.data);
  else if (ev.event === "decision" && onDecision) onDecision(ev.data);
  else if (ev.event === "action" && onAction) onAction(ev.data);
  else if (ev.event === "proof" && onProof) onProof(ev.data);
  else if (ev.event === "phase" && onPhase) onPhase(ev.data);
}

/** Build auth headers for integrate-anywhere (API key and/or license). */
export function authHeaders({ apiKey, license, extra } = {}) {
  const h = { "Content-Type": "application/json", ...(extra || {}) };
  const key = apiKey || (typeof process !== "undefined" && process.env && process.env.LOLM_API_KEY) || "";
  const lic = license || (typeof process !== "undefined" && process.env && process.env.LOLM_LICENSE) || "";
  if (key) h["X-LOLM-Api-Key"] = key;
  if (lic) h["X-LOLM-License"] = lic;
  return h;
}

/**
 * Run the agent live against a LOLM-NFET workspace and stream its events.
 *
 * @param {Object} opts
 * @param {string} [opts.baseUrl="https://lolm.imagineqira.com"] workspace origin
 * @param {string} [opts.endpoint="/api/demo/run/stream"] public demo endpoint;
 *   use "/api/agent/nfet/run/stream" against your own local workspace
 * @param {string} opts.command the instruction for the agent
 * @param {Array<{role:string,content:string}>} [opts.history] prior turns of THIS
 *   conversation → in-conversation memory (resolves "it/that/what I just asked")
 * @param {string[]} [opts.memory] durable facts about the user → cross-session memory
 *   (the agent recalls them in every conversation). See getMemory()/rememberFact().
 * @param {Object} [opts.body] extra request fields (budgets etc., local endpoint only)
 * @param {AbortSignal} [opts.signal]
 * @param {Function} [opts.onEvent] every protocol event `{event, data}`
 * @param {Function} [opts.onToken] `{token, channel, segment?, nfet?}`
 * @param {Function} [opts.onDecision] decision entries with z-scores and source
 * @param {Function} [opts.onAction] dispatched actions (retrieve/verify/branch/...)
 * @param {Function} [opts.onProof] the proof receipt
 * @param {Function} [opts.onPhase] phase markers
 * @param {Function} [opts.fetch] custom fetch (defaults to global)
 * @returns {Promise<Object>} the `run_done` payload
 */
export async function runAgent(opts) {
  const {
    baseUrl = "https://lolm.imagineqira.com",
    endpoint = "/api/demo/run/stream",
    command,
    history,
    memory,
    body = {},
    signal, timeoutMs = DEFAULT_TIMEOUT_MS,
    idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS,
    fetch: fetchImpl = globalThis.fetch,
  } = opts;
  if (!command || !command.trim()) throw new AgentRunError("command is required");
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");

  const payload = { command, ...body };
  if (Array.isArray(history) && history.length) payload.history = history;
  if (Array.isArray(memory) && memory.length) payload.user_memory = memory;

  const scope = networkScope({ signal, timeoutMs, idleTimeoutMs });
  try {
    const resp = await fetchImpl(new URL(endpoint, baseUrl), {
      method: "POST",
      headers: authHeaders({ apiKey: opts.apiKey, license: opts.license }),
      body: JSON.stringify(payload),
      signal: scope.signal,
    });
    if (!resp.ok) {
      let parsed = null;
      try { parsed = await readJsonResponse(resp, opts.maxResponseBytes); } catch { /* not json */ }
      throw new AgentRunError(
        (parsed && parsed.error) || `run refused with HTTP ${resp.status}`,
        { status: resp.status, body: parsed, code: "HTTP_ERROR" },
      );
    }

    let result = null;
    for await (const ev of parseSSEStream(resp.body, {
      maxEventBytes: opts.maxEventBytes,
      maxStreamBytes: opts.maxStreamBytes,
      onActivity: scope.touch,
    })) {
      dispatch(ev, opts);
      if (ev.event === "run_done") result = ev.data;
      if (ev.event === "error") {
        throw new AgentRunError(
          (ev.data && ev.data.error) || "stream reported an error",
          { body: ev.data, code: "STREAM_ERROR" },
        );
      }
    }
    if (!result) throw new AgentRunError("stream ended without run_done", { code: "MISSING_RUN_DONE" });
    return result;
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}

const REPLAY_DELAYS = { token: 18, decision: 750, action: 600, default: 180 };

/**
 * Play a recorded replay (as produced by the workspace's replay recorder)
 * through the same handlers as a live run.
 *
 * @param {string|Object|Array} source replay URL, `{events: [...]}` object,
 *   or a bare event array
 * @param {Object} [opts]
 * @param {number} [opts.speed=1] pacing multiplier; `0` = instant
 * @param {AbortSignal} [opts.signal]
 * @returns {Promise<Object|null>} the `run_done` payload if present
 */
export async function playReplay(source, opts = {}) {
  const { speed = 1, signal, fetch: fetchImpl = globalThis.fetch,
    timeoutMs = DEFAULT_TIMEOUT_MS, maxResponseBytes = DEFAULT_JSON_BYTES } = opts;
  let events = source;
  if (typeof source === "string") {
    const scope = networkScope({ signal, timeoutMs });
    try {
      const resp = await fetchImpl(source, { signal: scope.signal });
      if (!resp.ok) throw new AgentRunError(`replay fetch failed: HTTP ${resp.status}`, {
        status: resp.status, code: "HTTP_ERROR",
      });
      events = await readJsonResponse(resp, maxResponseBytes);
    } catch (error) {
      throw scope.error(error);
    } finally {
      scope.cleanup();
    }
  }
  if (events && !Array.isArray(events)) events = events.events;
  if (!Array.isArray(events)) throw new AgentRunError("replay source has no events");

  let result = null;
  for (const ev of events) {
    if (signal && signal.aborted) throw new AgentRunError("replay aborted");
    dispatch(ev, opts);
    if (ev.event === "run_done") result = ev.data;
    if (speed > 0) {
      const wait = (REPLAY_DELAYS[ev.event] ?? REPLAY_DELAYS.default) / speed;
      await new Promise((r) => setTimeout(r, wait));
    }
  }
  return result;
}

const ENDED = {
  nfet_finalize: "it decided on its own that it was done",
  draft_cap_finalize: "it finished the answer after drafting",
  audit_verified: "it double-checked a high-stakes answer and finished",
  natural_eos: "it reached a natural stopping point",
  // Rare: only when no answer could be produced. Never preferred UX copy.
  segment_budget: "the run hit a safety backstop before an answer formed",
  repetition_stall: "it stopped when the draft had nothing new to add",
  social_direct: "it answered a greeting directly",
  dialog_direct: "it answered in conversation mode",
};

/**
 * Plain-English narration for a protocol event — the same voice as the
 * public Try page. Returns `null` for events with nothing worth saying
 * (individual tokens, for instance).
 */
export function friendly(ev) {
  const { event, data } = ev;
  if (event === "run_start") return "Reading the question…";
  if (event === "segment_start") return data.segment === 1 ? "Starting a draft" : null;
  if (event === "decision") {
    const d = data.decision || {};
    const WHY = {
      head: "its trained controller called this",
      budget: "control budget used — kept writing instead",
      last_segment: "wrapping up on the final draft pass",
      profile: "it recognized a simple greeting",
      repetition: "the draft stopped adding anything new",
      heuristic: "its built-in instincts called this",
      audit: "high-stakes check",
    };
    const why = WHY[d.source] || WHY.heuristic;
    if (d.source === "profile") return `Simple greeting — answering directly (${why})`;
    if (d.label === "retrieve") return `It noticed it wasn't sure — checking its notes (${why})`;
    if (d.label === "verify") return `Something felt off — double-checking the draft (${why})`;
    if (d.label === "branch") return `It felt stuck — trying two directions (${why})`;
    if (d.label === "finalize") return `It feels confident — finishing up (${why})`;
    return null;
  }
  if (event === "action") {
    if (data.kind === "retrieve") return `Found ${data.added} useful note${data.added === 1 ? "" : "s"}`;
    if (data.kind === "verify") return data.verdict === "revise"
      ? "It caught an issue in its own draft and noted a fix"
      : "The draft checks out";
    if (data.kind === "branch") return "Kept the steadier of its drafts";
    return null;
  }
  if (event === "phase") {
    if (data.phase === "finalize") return "Writing the final answer…";
    if (data.phase === "base_comparison") return "Comparing against a plain chatbot answer";
    return null;
  }
  if (event === "proof") {
    const v = data.verdict;
    if (v === "nfet_control_visible") return "It acted on its own uncertainty — and the answer clearly differs from a plain chatbot's.";
    if (v === "nfet_finalize_visible") return "It decided for itself when it was done — and the answer differs from a plain chatbot's.";
    if (v === "social_direct_reply") return "Simple greeting — it noticed, skipped the machinery, and just answered.";
    if (v === "changed_but_controls_quiet") return "It stayed confident the whole way — no checks needed this time.";
    return "This run didn't clearly beat a plain chatbot — some runs are like that.";
  }
  if (event === "code_start") return "Opening an isolated code sandbox…";
  if (event === "file_changed") return data && data.path ? `Writing ${data.path}` : "Writing a file";
  if (event === "command_started") return data && data.command ? `Running \`${String(data.command).slice(0, 60)}\`` : "Running a command";
  if (event === "command_finished") {
    const code = data && (data.blocked ? "blocked" : data.exit_code);
    return code === 0 ? "Command succeeded" : `Command exited ${code}`;
  }
  if (event === "code_done") return data && data.ok ? "Coding loop finished — verified." : "Coding loop finished.";
  if (event === "code_receipt") {
    const sha = data && data.receipt_sha ? String(data.receipt_sha).slice(0, 12) : "";
    return sha ? `Sealed code receipt ${sha}…` : "Sealed a code receipt.";
  }
  if (event === "visual_receipt") {
    const sha = data && data.receipt_sha ? String(data.receipt_sha).slice(0, 12) : "";
    const ok = data && data.ok;
    return (ok ? "Verified visual build" : "Visual build finished") + (sha ? ` · receipt ${sha}…` : "");
  }
  if (event === "learned") {
    const n = Array.isArray(data && data.items) ? data.items.length : (data && data.text ? 1 : 0);
    return n ? `Remembered ${n} fact${n === 1 ? "" : "s"} for later` : "Saved something to memory";
  }
  if (event === "continuity_tick") {
    const facts = (data && data.facts) || [];
    if (data && data.model_used) return "Local continuity tick refined thread memory";
    if (facts.length) return `Promoted ${facts.length} continuity fact${facts.length === 1 ? "" : "s"}`;
    return data && data.promoted ? "Updated continuity memory" : null;
  }
  if (event === "run_done") {
    const base = data.ended_by && ENDED[data.ended_by] ? `Done — ${ENDED[data.ended_by]}.` : "Done.";
    if (Array.isArray(data.provenance) && data.provenance.length) {
      return `${base} What it actually did: ${data.provenance.join(" · ")}`;
    }
    return base;
  }
  if (event === "error") return `Hit a snag: ${(data && data.error) || "unknown"}`;
  return null;
}

/** Fetch a workspace's demo status (model readiness, busy flag, limits). */
export async function getStatus({ baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch,
  signal, timeoutMs = DEFAULT_TIMEOUT_MS, maxResponseBytes = DEFAULT_JSON_BYTES } = {}) {
  const scope = networkScope({ signal, timeoutMs });
  try {
    const resp = await fetchImpl(new URL("/api/demo/status", baseUrl), { signal: scope.signal });
    if (!resp.ok) throw new AgentRunError(`status failed: HTTP ${resp.status}`, { status: resp.status, code: "HTTP_ERROR" });
    return await readJsonResponse(resp, maxResponseBytes);
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}

/**
 * Build a self-contained, sandboxed visual app (game / animation / page) from a
 * prompt. Returns one complete HTML document — render it in a sandboxed iframe
 * (`<iframe sandbox="allow-scripts" srcdoc={html}>`); the browser is the runtime.
 * @returns {Promise<{html:string, bytes:number}>}
 */
export async function buildVisual({ task, baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch,
  signal, apiKey, license, timeoutMs = DEFAULT_TIMEOUT_MS,
  idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS, maxEventBytes = DEFAULT_SSE_EVENT_BYTES,
  maxStreamBytes = DEFAULT_SSE_STREAM_BYTES, onEvent } = {}) {
  if (!task || !task.trim()) throw new AgentRunError("task is required");
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");
  const scope = networkScope({ signal, timeoutMs, idleTimeoutMs });
  try {
    const resp = await fetchImpl(new URL("/api/demo/code/visual/build", baseUrl), {
      method: "POST",
      headers: authHeaders({ apiKey, license }),
      body: JSON.stringify({ task }), signal: scope.signal,
    });
    if (!resp.ok) {
      let body = {};
      try { body = await readJsonResponse(resp); } catch { /* not json */ }
      throw new AgentRunError(body.error || `visual build failed: HTTP ${resp.status}`,
        { status: resp.status, body, code: "HTTP_ERROR" });
    }
    let done = null;
    let receipt = null;
    for await (const event of parseSSEStream(resp.body, {
      maxEventBytes, maxStreamBytes, onActivity: scope.touch,
    })) {
      onEvent?.(event);
      if (event.event === "done") done = event.data;
      if (event.event === "visual_receipt") receipt = event.data;
      if (event.event === "error") throw new AgentRunError(
        event.data?.error || "visual build stream error", { body: event.data, code: "STREAM_ERROR" });
    }
    if (!done) throw new AgentRunError("stream ended without visual done", { code: "MISSING_VISUAL_DONE" });
    if (!receipt) throw new AgentRunError("stream ended without visual receipt", { code: "MISSING_VISUAL_RECEIPT" });
    if (!done.run_id || !receipt.run_id || done.run_id !== receipt.run_id) {
      throw new AgentRunError("visual done and receipt run_id do not match", {
        code: "VISUAL_RUN_MISMATCH",
      });
    }
    return { ...done, receipt };
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}

/**
 * Run the agentic coding loop: the model writes real code, runs it in a network-
 * isolated bwrap jail, reads the failure, and fixes it — streamed as SSE. Same
 * handler shape as runAgent (`onEvent`); events: code_start / file_changed /
 * command_started / command_finished / agent_note / code_done / code_receipt / error.
 * @returns {Promise<Object>} `{ done, receipt }` — `done` is code_done, `receipt`
 *   is the sealed (and server-ledger-chained) code_receipt when present
 */
export async function runCode(opts) {
  const { task, baseUrl = "https://lolm.imagineqira.com", maxSteps, history, signal,
    timeoutMs = DEFAULT_TIMEOUT_MS, idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS,
    webhookUrl, conversationId, resumePackage, resumeToken,
    fetch: fetchImpl = globalThis.fetch } = opts;
  if (!task || !task.trim()) throw new AgentRunError("task is required");
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");
  const scope = networkScope({ signal, timeoutMs, idleTimeoutMs });
  try {
    const resp = await fetchImpl(new URL("/api/demo/code/run", baseUrl), {
      method: "POST",
      headers: authHeaders({ apiKey: opts.apiKey, license: opts.license }),
      body: JSON.stringify({
        task,
        ...(maxSteps ? { max_steps: maxSteps } : {}),
        ...(history ? { history } : {}),
        ...(webhookUrl ? { webhook_url: webhookUrl } : {}),
        ...(conversationId ? { conversation_id: conversationId } : {}),
        ...(resumePackage ? { resume_package: resumePackage } : {}),
        ...(resumeToken ? { resume_token: resumeToken } : {}),
      }), signal: scope.signal,
    });
    if (!resp.ok) {
      let p = null; try { p = await readJsonResponse(resp, opts.maxResponseBytes); } catch { /* not json */ }
      throw new AgentRunError((p && p.error) || `code run refused: HTTP ${resp.status}`, { status: resp.status, body: p, code: "HTTP_ERROR" });
    }
    let result = null;
    let receipt = null;
    for await (const ev of parseSSEStream(resp.body, {
      maxEventBytes: opts.maxEventBytes,
      maxStreamBytes: opts.maxStreamBytes,
      onActivity: scope.touch,
    })) {
      if (opts.onEvent) opts.onEvent(ev);
      if (ev.event === "code_done") {
        result = ev.data;
        if (opts.onCodeDone) opts.onCodeDone(ev.data);
      }
      if (ev.event === "code_receipt") {
        receipt = ev.data;
        if (opts.onCodeReceipt) opts.onCodeReceipt(ev.data);
      }
      if (ev.event === "error") throw new AgentRunError((ev.data && ev.data.error) || "code stream error", { body: ev.data, code: "STREAM_ERROR" });
    }
    if (!result || typeof result !== "object") {
      throw new AgentRunError("stream ended without code_done", { code: "MISSING_CODE_DONE" });
    }
    // Back-compat: callers that checked .ran keep done fields on the root.
    result.receipt = receipt;
    result.receipt_sha = (receipt && receipt.receipt_sha) || result.receipt_sha;
    return result;
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}

/** Recent sealed code receipts from the public audit ledger. */
export async function listCodeReceipts({ baseUrl = "https://lolm.imagineqira.com", limit = 20,
  fetch: fetchImpl = globalThis.fetch, signal, timeoutMs = DEFAULT_TIMEOUT_MS,
  maxResponseBytes = DEFAULT_JSON_BYTES } = {}) {
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");
  const url = new URL("/api/demo/code/receipts", baseUrl);
  if (limit) url.searchParams.set("limit", String(limit));
  const scope = networkScope({ signal, timeoutMs });
  try {
    const resp = await fetchImpl(url, { signal: scope.signal });
    if (!resp.ok) throw new AgentRunError(`code receipts failed: HTTP ${resp.status}`, { status: resp.status, code: "HTTP_ERROR" });
    return await readJsonResponse(resp, maxResponseBytes);
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}

// ── cross-session memory (authenticated principal scoped) ────────────────────
function memHeaders({ apiKey, license } = {}) {
  const key = apiKey
    || (typeof process !== "undefined" && process.env && process.env.LOLM_API_KEY)
    || "";
  if (!key) {
    throw new AgentRunError("authentication required for persistent memory");
  }
  return authHeaders({ apiKey: key, license });
}

/** List the durable facts remembered about a user (recalled in every conversation). */
export async function getMemory({ apiKey, license, baseUrl = "https://lolm.imagineqira.com",
  fetch: fetchImpl = globalThis.fetch, signal, timeoutMs = DEFAULT_TIMEOUT_MS,
  maxResponseBytes = DEFAULT_JSON_BYTES } = {}) {
  const scope = networkScope({ signal, timeoutMs });
  try {
    const resp = await fetchImpl(new URL("/api/demo/workspace/memory", baseUrl), {
      headers: memHeaders({ apiKey, license }), signal: scope.signal,
    });
    if (!resp.ok) throw new AgentRunError(`memory list failed: HTTP ${resp.status}`, { status: resp.status, code: "HTTP_ERROR" });
    return (await readJsonResponse(resp, maxResponseBytes)).memories || [];
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}

/**
 * Remember a durable fact about the user. By default stores `text` verbatim; pass
 * `extract:true` to let the model pull the durable fact(s) out of a raw message.
 * @returns {Promise<Object>} `{saved}` (verbatim) or `{saved:[...]}` (extract)
 */
export async function rememberFact({ text, apiKey, license, extract = false,
  baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch,
  signal, timeoutMs = DEFAULT_TIMEOUT_MS, maxResponseBytes = DEFAULT_JSON_BYTES } = {}) {
  if (!text || !text.trim()) throw new AgentRunError("text is required");
  const url = new URL(extract ? "/api/demo/workspace/memory/extract" : "/api/demo/workspace/memory", baseUrl);
  const scope = networkScope({ signal, timeoutMs });
  try {
    const resp = await fetchImpl(url, { method: "POST", headers: memHeaders({ apiKey, license }),
      body: JSON.stringify(extract ? { user_message: text } : { text }), signal: scope.signal });
    if (!resp.ok) throw new AgentRunError(`remember failed: HTTP ${resp.status}`, { status: resp.status, code: "HTTP_ERROR" });
    return await readJsonResponse(resp, maxResponseBytes);
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}

/** Forget one fact by `id`, or clear everything for the authenticated principal. */
export async function forgetMemory({ id, all = false, apiKey, license,
  baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch,
  signal, timeoutMs = DEFAULT_TIMEOUT_MS, maxResponseBytes = DEFAULT_JSON_BYTES } = {}) {
  const url = new URL(all ? "/api/demo/workspace/memory/clear" : `/api/demo/workspace/memory/${id}`, baseUrl);
  const scope = networkScope({ signal, timeoutMs });
  try {
    const resp = await fetchImpl(url, { method: all ? "POST" : "DELETE",
      headers: memHeaders({ apiKey, license }), signal: scope.signal });
    if (!resp.ok) throw new AgentRunError(`forget failed: HTTP ${resp.status}`, { status: resp.status, code: "HTTP_ERROR" });
    return await readJsonResponse(resp, maxResponseBytes);
  } catch (error) {
    throw scope.error(error);
  } finally {
    scope.cleanup();
  }
}
