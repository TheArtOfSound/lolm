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
    body = {},
    signal,
    fetch: fetchImpl = globalThis.fetch,
  } = opts;
  if (!command || !command.trim()) throw new AgentRunError("command is required");
  if (!fetchImpl) throw new AgentRunError("no fetch available; pass opts.fetch");

  const resp = await fetchImpl(new URL(endpoint, baseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, ...body }),
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
    const why = d.source === "head" ? "its trained controller called this"
      : d.source === "budget" ? "limit reached — kept writing instead"
      : "its built-in instincts called this";
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
    if (v === "changed_but_controls_quiet") return "It stayed confident the whole way — no checks needed this time.";
    return "This run didn't clearly beat a plain chatbot — some runs are like that.";
  }
  if (event === "run_done") return data.ended_by && ENDED[data.ended_by]
    ? `Done — ${ENDED[data.ended_by]}.` : "Done.";
  if (event === "error") return `Hit a snag: ${(data && data.error) || "unknown"}`;
  return null;
}

/** Fetch a workspace's demo status (model readiness, busy flag, limits). */
export async function getStatus({ baseUrl = "https://lolm.imagineqira.com", fetch: fetchImpl = globalThis.fetch, signal } = {}) {
  const resp = await fetchImpl(new URL("/api/demo/status", baseUrl), { signal });
  if (!resp.ok) throw new AgentRunError(`status failed: HTTP ${resp.status}`, { status: resp.status });
  return resp.json();
}
