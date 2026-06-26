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
  constructor(message, { status = null, body = null } = {}) {
    super(message);
    this.name = "AgentRunError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Parse a fetch-response body (ReadableStream) of Server-Sent Events into
 * `{event, data}` objects. `data:` payloads are JSON-parsed.
 */
export async function* parseSSEStream(stream) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = null;
        let data = null;
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7).trim();
          else if (line.startsWith("data: ")) {
            const raw = line.slice(6);
            try { data = JSON.parse(raw); } catch { data = raw; }
          }
        }
        if (event) yield { event, data };
      }
    }
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
    signal,
    fetch: fetchImpl = globalThis.fetch,
  } = opts;
  if (!command || !command.trim()) throw new AgentRunError("command is required");
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");

  const payload = { command, ...body };
  if (Array.isArray(history) && history.length) payload.history = history;
  if (Array.isArray(memory) && memory.length) payload.user_memory = memory;

  const resp = await fetchImpl(new URL(endpoint, baseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!resp.ok) {
    let parsed = null;
    try { parsed = await resp.json(); } catch { /* not json */ }
    throw new AgentRunError(
      (parsed && parsed.error) || `run refused with HTTP ${resp.status}`,
      { status: resp.status, body: parsed },
    );
  }

  let result = null;
  for await (const ev of parseSSEStream(resp.body)) {
    dispatch(ev, opts);
    if (ev.event === "run_done") result = ev.data;
    if (ev.event === "error") {
      throw new AgentRunError(
        (ev.data && ev.data.error) || "stream reported an error",
        { body: ev.data },
      );
    }
  }
  if (!result) throw new AgentRunError("stream ended without run_done");
  return result;
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
  const { speed = 1, signal, fetch: fetchImpl = globalThis.fetch } = opts;
  let events = source;
  if (typeof source === "string") {
    const resp = await fetchImpl(source, { signal });
    if (!resp.ok) throw new AgentRunError(`replay fetch failed: HTTP ${resp.status}`, { status: resp.status });
    events = await resp.json();
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
  natural_eos: "it reached a natural stopping point",
  segment_budget: "it hit the length limit",
  repetition_stall: "it stopped when the draft had nothing new to add",
  social_direct: "it answered a greeting directly",
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
      budget: "limit reached — kept writing instead",
      profile: "it recognized a simple greeting",
      repetition: "the draft stopped adding anything new",
      heuristic: "its built-in instincts called this",
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
export async function getStatus({ baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch, signal } = {}) {
  const resp = await fetchImpl(new URL("/api/demo/status", baseUrl), { signal });
  if (!resp.ok) throw new AgentRunError(`status failed: HTTP ${resp.status}`, { status: resp.status });
  return resp.json();
}

/**
 * Build a self-contained, sandboxed visual app (game / animation / page) from a
 * prompt. Returns one complete HTML document — render it in a sandboxed iframe
 * (`<iframe sandbox="allow-scripts" srcdoc={html}>`); the browser is the runtime.
 * @returns {Promise<{html:string, bytes:number}>}
 */
export async function buildVisual({ task, baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch, signal } = {}) {
  if (!task || !task.trim()) throw new AgentRunError("task is required");
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");
  const resp = await fetchImpl(new URL("/api/demo/code/visual", baseUrl), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }), signal,
  });
  const j = await resp.json().catch(() => ({}));
  if (!resp.ok || !j.html) throw new AgentRunError(j.error || `visual build failed: HTTP ${resp.status}`, { status: resp.status, body: j });
  return j;
}

/**
 * Run the agentic coding loop: the model writes real code, runs it in a network-
 * isolated bwrap jail, reads the failure, and fixes it — streamed as SSE. Same
 * handler shape as runAgent (`onEvent`); events: code_start / file_changed /
 * command_started / command_finished / agent_note / code_done / error.
 * @returns {Promise<Object>} the `code_done` payload
 */
export async function runCode(opts) {
  const { task, baseUrl = "https://lolm.imagineqira.com", maxSteps, signal, fetch: fetchImpl = globalThis.fetch } = opts;
  if (!task || !task.trim()) throw new AgentRunError("task is required");
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");
  const resp = await fetchImpl(new URL("/api/demo/code/run", baseUrl), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, ...(maxSteps ? { max_steps: maxSteps } : {}) }), signal,
  });
  if (!resp.ok) {
    let p = null; try { p = await resp.json(); } catch { /* not json */ }
    throw new AgentRunError((p && p.error) || `code run refused: HTTP ${resp.status}`, { status: resp.status, body: p });
  }
  let result = null;
  for await (const ev of parseSSEStream(resp.body)) {
    if (opts.onEvent) opts.onEvent(ev);
    if (ev.event === "code_done") result = ev.data;
    if (ev.event === "error") throw new AgentRunError((ev.data && ev.data.error) || "code stream error", { body: ev.data });
  }
  return result;
}

// ── cross-session memory (owner-scoped; `owner` is a per-user key your app picks) ──
function memHeaders(owner) {
  const h = { "Content-Type": "application/json" };
  if (owner) h["X-Workspace-Owner"] = owner;
  return h;
}

/** List the durable facts remembered about a user (recalled in every conversation). */
export async function getMemory({ owner, baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch } = {}) {
  const resp = await fetchImpl(new URL("/api/demo/workspace/memory", baseUrl), { headers: memHeaders(owner) });
  if (!resp.ok) throw new AgentRunError(`memory list failed: HTTP ${resp.status}`, { status: resp.status });
  return (await resp.json()).memories || [];
}

/**
 * Remember a durable fact about the user. By default stores `text` verbatim; pass
 * `extract:true` to let the model pull the durable fact(s) out of a raw message.
 * @returns {Promise<Object>} `{saved}` (verbatim) or `{saved:[...]}` (extract)
 */
export async function rememberFact({ text, owner, extract = false, baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch } = {}) {
  if (!text || !text.trim()) throw new AgentRunError("text is required");
  const url = new URL(extract ? "/api/demo/workspace/memory/extract" : "/api/demo/workspace/memory", baseUrl);
  const resp = await fetchImpl(url, { method: "POST", headers: memHeaders(owner), body: JSON.stringify(extract ? { user_message: text } : { text }) });
  if (!resp.ok) throw new AgentRunError(`remember failed: HTTP ${resp.status}`, { status: resp.status });
  return resp.json();
}

/** Forget one fact by `id`, or pass `all:true` to clear everything for this owner. */
export async function forgetMemory({ id, all = false, owner, baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch } = {}) {
  const url = new URL(all ? "/api/demo/workspace/memory/clear" : `/api/demo/workspace/memory/${id}`, baseUrl);
  const resp = await fetchImpl(url, { method: all ? "POST" : "DELETE", headers: memHeaders(owner) });
  if (!resp.ok) throw new AgentRunError(`forget failed: HTTP ${resp.status}`, { status: resp.status });
  return resp.json();
}
