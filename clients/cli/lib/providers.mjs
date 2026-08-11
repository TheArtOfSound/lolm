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

async function request(url, runtime, { method = "POST", body, headers = {} } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error("provider request timed out")), runtime.timeoutMs);
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await fetch(url, {
        method,
        headers: { "content-type": "application/json", ...headers },
        body: body == null ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const text = await response.text();
      let payload = {};
      try { payload = text ? JSON.parse(text) : {}; } catch { payload = { raw: text.slice(0, 1000) }; }
      if (!response.ok) {
        if (response.status === 429 && attempt < 2) {
          const headerSeconds = Number(response.headers.get("retry-after"));
          const waitMs = Number.isFinite(headerSeconds) ? Math.max(0, headerSeconds * 1_000) : 12_000 * (attempt + 1);
          await new Promise((resolvePromise) => setTimeout(resolvePromise, Math.min(waitMs, 30_000)));
          continue;
        }
        const message = payload?.error?.message || payload?.error || payload?.message || `Provider returned HTTP ${response.status}`;
        throw new ProviderError(String(message), { status: response.status, code: payload?.error?.code || "HTTP_ERROR", body: payload });
      }
      return payload;
    }
    throw new ProviderError("Provider rate limit did not clear after bounded retries", { status: 429, code: "RATE_LIMITED" });
  } catch (error) {
    if (error instanceof ProviderError) throw error;
    const timeout = error?.name === "AbortError" || /timed out/i.test(error?.message || "");
    throw new ProviderError(timeout ? "Provider request timed out" : `Provider request failed: ${error.message}`, {
      code: timeout ? "TIMEOUT" : "NETWORK_ERROR",
    });
  } finally {
    clearTimeout(timer);
  }
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

function parseArguments(value) {
  if (value && typeof value === "object") return value;
  try { return JSON.parse(String(value || "{}")); } catch { return {}; }
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
    toolCalls: (message.tool_calls || []).map((call, index) => ({
      id: call.id || `call_${index}`,
      name: call.function?.name || "",
      arguments: parseArguments(call.function?.arguments),
    })),
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
    usage: payload.usage || null,
    raw: payload,
  };
}

function geminiContents(messages) {
  const contents = [];
  for (const message of messages.filter((item) => item.role !== "system")) {
    if (message.role === "assistant") {
      const parts = [];
      if (message.content) parts.push({ text: message.content });
      for (const call of message.toolCalls || []) parts.push({ functionCall: { name: call.name, args: call.arguments || {} } });
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
      ...(tools.length ? { tools: [{ functionDeclarations: tools.map((tool) => tool.function) }] } : {}),
    },
  });
  const parts = payload?.candidates?.[0]?.content?.parts || [];
  return {
    content: parts.map((part) => part.text || "").join(""),
    toolCalls: parts.filter((part) => part.functionCall).map((part, index) => ({
      id: `gemini_${index}_${Date.now()}`,
      name: part.functionCall.name || "",
      arguments: part.functionCall.args || {},
    })),
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
