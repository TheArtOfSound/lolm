// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Minimal provider adapters: OpenAI-compatible, Anthropic, Gemini, and Ollama. */

export class ProviderError extends Error {
  constructor(message, { status = 0, code = "PROVIDER_ERROR", body = null } = {}) {
    super(message);
    this.name = "ProviderError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function endpoint(base, suffix) {
  return `${String(base).replace(/\/+$/, "")}${suffix}`;
}

const RATE_LIMIT_ATTEMPTS = 5;
const MAX_BACKOFF_MS = 65_000;

/** A per-minute rate limit clears on its own; a spent daily allowance does not,
 *  so waiting on one only burns the user's time. */
function quotaIsExhausted(payload, text) {
  const haystack = `${JSON.stringify(payload?.error || "")} ${text}`.toLowerCase();
  if (/per\s*day|daily|"?requests_per_day"?|perday/.test(haystack)) return true;
  return /exhausted your daily|quota exceeded.*limit:\s*0\b/.test(haystack);
}

/** Providers disagree on where the wait lives: a header, a structured RetryInfo
 *  duration, or only the prose of the error message. Read all three. */
function retryDelayMs(response, payload, text, attempt) {
  const header = Number(response.headers.get("retry-after"));
  if (Number.isFinite(header) && header > 0) return header * 1_000;
  const details = payload?.error?.details;
  if (Array.isArray(details)) {
    for (const detail of details) {
      const seconds = Number(String(detail?.retryDelay || "").replace(/s$/, ""));
      if (Number.isFinite(seconds) && seconds > 0) return seconds * 1_000;
    }
  }
  const prose = /retry in ([\d.]+)\s*s/i.exec(text);
  if (prose) return Math.ceil(Number(prose[1]) * 1_000);
  return 2_000 * 2 ** attempt;
}

async function request(url, runtime, { method = "POST", body, headers = {} } = {}) {
  let lastRateLimit = null;
  for (let attempt = 0; attempt < RATE_LIMIT_ATTEMPTS; attempt++) {
    // Each attempt gets its own deadline. A single timer spanning the retries
    // would abort a request that was only ever waiting out someone's throttle.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error("provider request timed out")), runtime.timeoutMs);
    let response;
    let text;
    try {
      response = await fetch(url, {
        method,
        headers: { "content-type": "application/json", ...headers },
        body: body == null ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      text = await response.text();
    } catch (error) {
      const timeout = error?.name === "AbortError" || /timed out/i.test(error?.message || "");
      throw new ProviderError(timeout ? "Provider request timed out" : `Provider request failed: ${error.message}`, {
        code: timeout ? "TIMEOUT" : "NETWORK_ERROR",
      });
    } finally {
      clearTimeout(timer);
    }

    let payload = {};
    try { payload = text ? JSON.parse(text) : {}; } catch { payload = { raw: text.slice(0, 1000) }; }

    // Some OpenAI-compatible routers — OpenRouter's free tier especially — answer
    // HTTP 200 with an error object and no choices. Handle it as the error it is,
    // so a throttle is retried and classified instead of surfacing one turn later
    // as an opaque "response did not contain a message".
    if (response.ok && payload && payload.error && !payload.choices) {
      const message = String(payload.error?.message || payload.error);
      const throttled = /\brate|limit|overloaded|capacity|temporarily|timeout|503|429\b/i.test(message);
      if (throttled && !quotaIsExhausted(payload, text) && attempt < RATE_LIMIT_ATTEMPTS - 1) {
        lastRateLimit = message;
        await new Promise((resolvePromise) => setTimeout(resolvePromise, Math.min(retryDelayMs(response, payload, text, attempt), MAX_BACKOFF_MS)));
        continue;
      }
      throw new ProviderError(message, { status: 200, code: payload.error?.code || (throttled ? "RATE_LIMITED" : "PROVIDER_ERROR"), body: payload });
    }
    if (response.ok) return payload;

    const message = String(payload?.error?.message || payload?.error || payload?.message || `Provider returned HTTP ${response.status}`);
    const retryable = response.status === 429 || response.status === 503;
    if (retryable && !quotaIsExhausted(payload, text) && attempt < RATE_LIMIT_ATTEMPTS - 1) {
      lastRateLimit = message;
      const waitMs = Math.min(retryDelayMs(response, payload, text, attempt), MAX_BACKOFF_MS);
      await new Promise((resolvePromise) => setTimeout(resolvePromise, waitMs));
      continue;
    }
    throw new ProviderError(message, {
      status: response.status,
      code: payload?.error?.code || (retryable ? "RATE_LIMITED" : "HTTP_ERROR"),
      body: payload,
    });
  }
  throw new ProviderError(lastRateLimit || "Provider rate limit did not clear after bounded retries", {
    status: 429,
    code: "RATE_LIMITED",
  });
}

async function streamJsonLines(url, runtime, { body, headers = {}, onValue = () => {} } = {}) {
  const controller = new AbortController();
  let timer;
  const armTimeout = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(new Error("provider stream became inactive")), runtime.timeoutMs);
  };
  armTimeout();
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      let payload = {};
      try { payload = text ? JSON.parse(text) : {}; } catch { payload = { raw: text.slice(0, 1000) }; }
      const message = payload?.error?.message || payload?.error || payload?.message || `Provider returned HTTP ${response.status}`;
      throw new ProviderError(String(message), { status: response.status, code: payload?.error?.code || "HTTP_ERROR", body: payload });
    }
    if (!response.body) throw new ProviderError("Provider response did not contain a stream", { code: "MALFORMED_RESPONSE" });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      armTimeout();
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try { onValue(JSON.parse(line)); }
        catch { throw new ProviderError("Provider returned malformed streaming JSON", { code: "MALFORMED_RESPONSE" }); }
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) onValue(JSON.parse(buffer));
  } catch (error) {
    if (error instanceof ProviderError) throw error;
    const timeout = error?.name === "AbortError" || /inactive|timed out/i.test(error?.message || "");
    throw new ProviderError(timeout
      ? `The provider stopped responding for ${Math.round(runtime.timeoutMs / 1000)} seconds.`
      : `Provider request failed: ${error.message}`, {
      code: timeout ? "TIMEOUT" : "NETWORK_ERROR",
    });
  } finally {
    clearTimeout(timer);
  }
}

/** Tool arguments arrive as a JSON string. When the completion is cut off at the
 *  token limit that string is unterminated, and silently degrading it to `{}`
 *  reports "path is required" for what is really a truncated response — so the
 *  model retries the same oversized write until the step budget is gone. Keep
 *  the real cause attached to the call. */
function parseArguments(value) {
  if (value && typeof value === "object") return { arguments: value, malformed: null };
  const text = String(value ?? "").trim();
  if (!text) return { arguments: {}, malformed: null };
  try {
    return { arguments: JSON.parse(text), malformed: null };
  } catch (error) {
    return { arguments: {}, malformed: { reason: error.message, length: text.length } };
  }
}

function toolCall(id, name, rawArguments, index) {
  const parsed = parseArguments(rawArguments);
  return { id: id || `call_${index}`, name: name || "", arguments: parsed.arguments, malformed: parsed.malformed };
}

function openAiMessages(messages) {
  return messages.map((message) => {
    if (message.role === "assistant" && message.toolCalls?.length) {
      return {
        role: "assistant",
        content: message.content || null,
        tool_calls: message.toolCalls.map((call) => ({
          id: call.id,
          type: "function",
          function: { name: call.name, arguments: JSON.stringify(call.arguments || {}) },
        })),
      };
    }
    if (message.role === "tool") {
      return { role: "tool", tool_call_id: message.id, content: String(message.content || "") };
    }
    return { role: message.role, content: String(message.content || "") };
  });
}

async function openAiChat(runtime, messages, tools = [], { maxTokens } = {}) {
  const suffix = runtime.baseUrl.endsWith("/v1") || runtime.baseUrl.includes("/api/v1")
    ? "/chat/completions" : "/v1/chat/completions";
  const payload = await request(endpoint(runtime.baseUrl, suffix), runtime, {
    headers: runtime.apiKey ? { authorization: `Bearer ${runtime.apiKey}` } : {},
    body: {
      model: runtime.model,
      messages: openAiMessages(messages),
      ...(maxTokens ? { max_tokens: maxTokens } : {}),
      ...(tools.length ? { tools, tool_choice: "auto" } : {}),
    },
  });
  const message = payload?.choices?.[0]?.message;
  if (!message) throw new ProviderError("Provider response did not contain a message", { code: "MALFORMED_RESPONSE", body: payload });
  return {
    content: typeof message.content === "string" ? message.content : Array.isArray(message.content)
      ? message.content.map((part) => part?.text || "").join("") : "",
    toolCalls: (message.tool_calls || []).map((call, index) => toolCall(call.id, call.function?.name, call.function?.arguments, index)),
    truncated: payload?.choices?.[0]?.finish_reason === "length",
    usage: payload.usage || null,
    raw: payload,
  };
}

function anthropicMessages(messages) {
  const out = [];
  for (const message of messages.filter((item) => item.role !== "system")) {
    if (message.role === "assistant") {
      const content = [];
      if (message.content) content.push({ type: "text", text: message.content });
      for (const call of message.toolCalls || []) content.push({ type: "tool_use", id: call.id, name: call.name, input: call.arguments || {} });
      out.push({ role: "assistant", content });
    } else if (message.role === "tool") {
      const prior = out.at(-1);
      const block = { type: "tool_result", tool_use_id: message.id, content: String(message.content || "") };
      if (prior?.role === "user" && Array.isArray(prior.content)) prior.content.push(block);
      else out.push({ role: "user", content: [block] });
    } else {
      out.push({ role: "user", content: String(message.content || "") });
    }
  }
  return out;
}

async function anthropicChat(runtime, messages, tools = [], { maxTokens } = {}) {
  const system = messages.filter((message) => message.role === "system").map((message) => message.content).join("\n\n");
  const payload = await request(endpoint(runtime.baseUrl, "/v1/messages"), runtime, {
    headers: { "x-api-key": runtime.apiKey, "anthropic-version": "2023-06-01" },
    body: {
      model: runtime.model,
      max_tokens: maxTokens || 8192,
      ...(system ? { system } : {}),
      messages: anthropicMessages(messages),
      ...(tools.length ? { tools: tools.map((tool) => ({
        name: tool.function.name,
        description: tool.function.description,
        input_schema: tool.function.parameters,
      })) } : {}),
    },
  });
  const blocks = payload.content || [];
  return {
    content: blocks.filter((block) => block.type === "text").map((block) => block.text).join(""),
    toolCalls: blocks.filter((block) => block.type === "tool_use").map((block, index) => ({
      id: block.id || `call_${index}`,
      name: block.name || "",
      arguments: block.input || {},
    })),
    truncated: payload?.stop_reason === "max_tokens",
    usage: payload.usage || null,
    raw: payload,
  };
}

// Gemini accepts an OpenAPI 3.0 subset, not full JSON Schema. Unknown keywords
// are a hard 400, so the tool registry's richer schema is projected down here
// instead of being weakened at the source.
const GEMINI_SCHEMA_KEYS = new Set([
  "type", "format", "description", "nullable", "enum", "items", "properties",
  "required", "minimum", "maximum", "minItems", "maxItems", "anyOf",
]);

function geminiSchema(schema) {
  if (!schema || typeof schema !== "object") return undefined;
  const types = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  const concrete = types.filter((type) => type !== "null");
  const out = {};
  for (const [key, value] of Object.entries(schema)) {
    if (!GEMINI_SCHEMA_KEYS.has(key)) continue;
    if (key === "type") continue;
    if (key === "properties") {
      const properties = {};
      for (const [name, child] of Object.entries(value || {})) {
        const mapped = geminiSchema(child);
        if (mapped) properties[name] = mapped;
      }
      if (Object.keys(properties).length) out.properties = properties;
      continue;
    }
    if (key === "items") {
      const mapped = geminiSchema(value);
      if (mapped) out.items = mapped;
      continue;
    }
    if (key === "anyOf") {
      const mapped = (value || []).map(geminiSchema).filter(Boolean);
      if (mapped.length) out.anyOf = mapped;
      continue;
    }
    out[key] = value;
  }
  // A union of scalar types has no OpenAPI equivalent; the widest honest
  // projection is the first concrete type, with null unions marked nullable.
  if (concrete.length) out.type = concrete[0].toUpperCase();
  if (types.includes("null")) out.nullable = true;
  if (out.type === "OBJECT" && !out.properties) return { type: "OBJECT", nullable: true, description: out.description };
  if (out.required) out.required = (out.required || []).filter((name) => out.properties?.[name]);
  if (Array.isArray(out.required) && !out.required.length) delete out.required;
  return Object.keys(out).length ? out : undefined;
}

function geminiTools(tools) {
  const declarations = [];
  for (const tool of tools) {
    const fn = tool.function || tool;
    if (!fn?.name) continue;
    const parameters = geminiSchema(fn.parameters);
    const declaration = { name: fn.name, description: fn.description || "" };
    // Gemini rejects a parameter object with no declared properties, so a
    // zero-argument tool must omit `parameters` entirely.
    if (parameters?.properties) declaration.parameters = parameters;
    declarations.push(declaration);
  }
  return declarations;
}

function geminiContents(messages) {
  const contents = [];
  for (const message of messages.filter((item) => item.role !== "system")) {
    if (message.role === "assistant") {
      const parts = [];
      // Gemini 3.x rejects a replayed turn whose thought signatures were
      // dropped, so each part is echoed back exactly as the model produced it.
      if (message.content) parts.push({ text: message.content, ...(message.signature ? { thoughtSignature: message.signature } : {}) });
      for (const call of message.toolCalls || []) {
        parts.push({
          functionCall: { name: call.name, args: call.arguments || {} },
          ...(call.signature ? { thoughtSignature: call.signature } : {}),
        });
      }
      contents.push({ role: "model", parts });
    } else if (message.role === "tool") {
      contents.push({ role: "user", parts: [{ functionResponse: { name: message.name, response: { result: message.content } } }] });
    } else {
      contents.push({ role: "user", parts: [{ text: String(message.content || "") }] });
    }
  }
  return contents;
}

async function geminiChat(runtime, messages, tools = [], { maxTokens } = {}) {
  const system = messages.filter((message) => message.role === "system").map((message) => message.content).join("\n\n");
  const url = endpoint(runtime.baseUrl, `/v1beta/models/${encodeURIComponent(runtime.model)}:generateContent`);
  const payload = await request(url, runtime, {
    headers: { "x-goog-api-key": runtime.apiKey },
    body: {
      contents: geminiContents(messages),
      ...(maxTokens ? { generationConfig: { maxOutputTokens: maxTokens } } : {}),
      ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}),
      ...(tools.length ? { tools: [{ functionDeclarations: geminiTools(tools) }] } : {}),
    },
  });
  const parts = payload?.candidates?.[0]?.content?.parts || [];
  return {
    content: parts.map((part) => part.text || "").join(""),
    signature: parts.find((part) => part.text && part.thoughtSignature)?.thoughtSignature || "",
    toolCalls: parts.filter((part) => part.functionCall).map((part, index) => ({
      id: `gemini_${index}_${Date.now()}`,
      name: part.functionCall.name || "",
      arguments: part.functionCall.args || {},
      signature: part.thoughtSignature || "",
    })),
    truncated: payload?.candidates?.[0]?.finishReason === "MAX_TOKENS",
    usage: payload.usageMetadata || null,
    raw: payload,
  };
}

function ollamaMessages(messages) {
  return messages.map((message) => {
    if (message.role === "assistant" && message.toolCalls?.length) {
      return {
        role: "assistant",
        content: message.content || "",
        tool_calls: message.toolCalls.map((call) => ({ function: { name: call.name, arguments: call.arguments || {} } })),
      };
    }
    if (message.role === "tool") return { role: "tool", tool_name: message.name, content: String(message.content || "") };
    return { role: message.role, content: String(message.content || "") };
  });
}

async function ollamaChat(runtime, messages, tools = [], { onToken = () => {}, reasoning, maxTokens } = {}) {
  let content = "", thinking = "", usage = null;
  const toolCalls = [];
  const requestBody = {
    model: runtime.model,
    messages: ollamaMessages(messages),
    stream: true,
    keep_alive: "30m",
    ...(maxTokens ? { options: { num_predict: maxTokens } } : {}),
    ...(typeof reasoning === "boolean" ? { think: reasoning } : {}),
    ...(tools.length ? { tools } : {}),
  };
  let doneReason = "";
  const consume = () => streamJsonLines(endpoint(runtime.baseUrl, "/api/chat"), runtime, {
    body: {
      ...requestBody,
    },
    onValue(payload) {
      const message = payload.message || {};
      if (message.content) {
        content += message.content;
        onToken(message.content, { content, thinking: false });
      }
      if (message.thinking) {
        thinking += message.thinking;
        onToken("", { content, thinking: true, thinkingChars: thinking.length });
      }
      for (const call of message.tool_calls || []) toolCalls.push(call);
      if (payload.done) {
        doneReason = payload.done_reason || "";
        usage = { prompt_tokens: payload.prompt_eval_count, completion_tokens: payload.eval_count };
      }
    },
  });
  try {
    await consume();
  } catch (error) {
    // A local Ollama runner can restart under memory pressure while the HTTP
    // daemon stays healthy. One bounded retry makes that recoverable without
    // hiding a persistent failure or retrying remote billable providers.
    if (error?.code !== "NETWORK_ERROR") throw error;
    content = ""; thinking = ""; usage = null; doneReason = ""; toolCalls.length = 0;
    await consume();
  }
  if (!content && !toolCalls.length) {
    throw new ProviderError("Provider response did not contain text or a tool call", {
      code: "MALFORMED_RESPONSE", body: { thinking_chars: thinking.length, done_reason: doneReason },
    });
  }
  return {
    content,
    toolCalls: toolCalls.map((call, index) => ({
      id: `ollama_${index}_${Date.now()}`,
      name: call.function?.name || "",
      arguments: parseArguments(call.function?.arguments),
    })),
    usage,
    raw: { streamed: true, thinking_chars: thinking.length },
  };
}

export async function chat(runtime, messages, { tools = [], onToken = () => {}, reasoning, maxTokens } = {}) {
  if (runtime.keyRequired && !runtime.apiKey) {
    throw new ProviderError(`No API key found for ${runtime.label}. Run 'lolm setup' or set the provider environment variable.`, { code: "AUTH_MISSING" });
  }
  if (runtime.protocol === "anthropic") return anthropicChat(runtime, messages, tools, { maxTokens });
  if (runtime.protocol === "gemini") return geminiChat(runtime, messages, tools, { maxTokens });
  if (runtime.protocol === "ollama") return ollamaChat(runtime, messages, tools, { onToken, reasoning, maxTokens });
  return openAiChat(runtime, messages, tools, { maxTokens });
}

export async function listModels(runtime) {
  if (runtime.keyRequired && !runtime.apiKey) throw new ProviderError(`No API key found for ${runtime.label}`, { code: "AUTH_MISSING" });
  if (runtime.protocol === "ollama") {
    const payload = await request(endpoint(runtime.baseUrl, "/api/tags"), runtime, { method: "GET" });
    return (payload.models || []).map((model) => model.name).filter(Boolean);
  }
  if (runtime.protocol === "gemini") {
    const payload = await request(endpoint(runtime.baseUrl, "/v1beta/models"), runtime, {
      method: "GET", headers: { "x-goog-api-key": runtime.apiKey },
    });
    return (payload.models || []).map((model) => String(model.name || "").replace(/^models\//, "")).filter(Boolean);
  }
  if (runtime.protocol === "anthropic") {
    const payload = await request(endpoint(runtime.baseUrl, "/v1/models"), runtime, {
      method: "GET", headers: { "x-api-key": runtime.apiKey, "anthropic-version": "2023-06-01" },
    });
    return (payload.data || []).map((model) => model.id).filter(Boolean);
  }
  const suffix = runtime.baseUrl.endsWith("/v1") || runtime.baseUrl.includes("/api/v1") ? "/models" : "/v1/models";
  const payload = await request(endpoint(runtime.baseUrl, suffix), runtime, {
    method: "GET", headers: runtime.apiKey ? { authorization: `Bearer ${runtime.apiKey}` } : {},
  });
  return (payload.data || payload.models || []).map((model) => model.id || model.name).filter(Boolean);
}

/** Read-only raw escape hatch for provider endpoints not yet modeled by LOLM. */
export async function rawGet(runtime, path) {
  const value = String(path || "").trim();
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("..")) {
    throw new ProviderError("raw request path must be an absolute provider path without '..'", { code: "INVALID_PATH" });
  }
  const headers = {};
  if (runtime.protocol === "gemini") headers["x-goog-api-key"] = runtime.apiKey;
  else if (runtime.protocol === "anthropic") {
    headers["x-api-key"] = runtime.apiKey;
    headers["anthropic-version"] = "2023-06-01";
  } else if (runtime.apiKey) headers.authorization = `Bearer ${runtime.apiKey}`;
  return request(endpoint(runtime.baseUrl, value), runtime, { method: "GET", headers });
}
