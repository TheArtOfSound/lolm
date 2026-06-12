/* In-browser answer engine — the last resilience tier.
 *
 * When every backend is unreachable (offline, box down, all quota gone), this
 * runs a small language model ENTIRELY in the visitor's browser via
 * transformers.js (WASM/WebGPU). No server, no quota, no network after the
 * one-time model download. It cannot run the LOLM graft (that needs PyTorch on
 * a backend), so it answers honestly WITHOUT the NFET control telemetry — the
 * receipt says so. The point is that an answer is always reachable.
 *
 * Loaded on demand (the library + model are ~heavy), never on page load.
 */

const OfflineEngine = (() => {
  const MODEL = "Xenova/Qwen2.5-0.5B-Instruct";   // ~0.5B, runs in-browser
  let pipe = null;
  let loading = null;

  async function ensure(onProgress) {
    if (pipe) return pipe;
    if (loading) return loading;
    loading = (async () => {
      const { pipeline, env } = await import(
        "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.0.2");
      env.allowLocalModels = false;
      pipe = await pipeline("text-generation", MODEL, {
        progress_callback: (p) => {
          if (onProgress && p && p.status === "progress" && p.file && p.progress != null) {
            onProgress({ file: p.file, pct: Math.round(p.progress) });
          }
        },
      });
      return pipe;
    })();
    return loading;
  }

  function ready() { return !!pipe; }

  async function answer(command, { onToken, onProgress, maxTokens = 256 } = {}) {
    const p = await ensure(onProgress);
    const messages = [
      { role: "system", content:
        "You are a concise, honest assistant. Answer the user's question directly. " +
        "If you do not know or the task is impossible, say so plainly." },
      { role: "user", content: command },
    ];
    let streamed = "";
    const out = await p(messages, {
      max_new_tokens: maxTokens,
      do_sample: true,
      temperature: 0.4,
      top_p: 0.9,
      // stream tokens to the caller as they generate
      callback_function: onToken ? (beams) => {
        try {
          const text = p.tokenizer.decode(beams[0].output_token_ids, { skip_special_tokens: true });
          const delta = text.slice(streamed.length);
          if (delta) { streamed = text; onToken(delta); }
        } catch (e) { /* decode mid-stream best-effort */ }
      } : undefined,
    });
    const full = Array.isArray(out) ? out[0].generated_text : out.generated_text;
    // generated_text is the chat array; take the last assistant turn
    if (Array.isArray(full)) {
      const last = full[full.length - 1];
      return (last && last.content ? last.content : "").trim();
    }
    return String(full || "").trim();
  }

  return { ensure, ready, answer, MODEL };
})();

if (typeof window !== "undefined") window.OfflineEngine = OfflineEngine;
