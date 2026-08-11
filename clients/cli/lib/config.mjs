// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Provider catalog and secure user configuration for the local LOLM CLI. */
import { mkdir, readFile, rename, writeFile, chmod } from "node:fs/promises";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import { getProviderSecret } from "./secrets.mjs";

export const CONFIG_PATH = process.env.LOLM_CONFIG || join(homedir(), ".lolm", "config.json");

export const PROVIDERS = Object.freeze({
  openai: {
    label: "OpenAI",
    protocol: "openai",
    baseUrl: "https://api.openai.com/v1",
    env: ["OPENAI_API_KEY"],
    model: "gpt-5.4",
  },
  anthropic: {
    label: "Anthropic",
    protocol: "anthropic",
    baseUrl: "https://api.anthropic.com",
    env: ["ANTHROPIC_API_KEY"],
    model: "claude-sonnet-4-6",
  },
  google: {
    label: "Google Gemini",
    protocol: "gemini",
    baseUrl: "https://generativelanguage.googleapis.com",
    env: ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    model: "gemini-3.5-flash",
  },
  xai: {
    label: "xAI",
    protocol: "openai",
    baseUrl: "https://api.x.ai/v1",
    env: ["XAI_API_KEY"],
    model: "grok-4-1-fast",
  },
  openrouter: {
    label: "OpenRouter",
    protocol: "openai",
    baseUrl: "https://openrouter.ai/api/v1",
    env: ["OPENROUTER_API_KEY"],
    model: "openai/gpt-5.4-mini",
  },
  groq: {
    label: "Groq",
    protocol: "openai",
    baseUrl: "https://api.groq.com/openai/v1",
    env: ["GROQ_API_KEY"],
    model: "openai/gpt-oss-120b",
  },
  mistral: {
    label: "Mistral",
    protocol: "openai",
    baseUrl: "https://api.mistral.ai/v1",
    env: ["MISTRAL_API_KEY"],
    model: "mistral-large-latest",
  },
  deepseek: {
    label: "DeepSeek",
    protocol: "openai",
    baseUrl: "https://api.deepseek.com/v1",
    env: ["DEEPSEEK_API_KEY"],
    model: "deepseek-chat",
  },
  together: {
    label: "Together AI",
    protocol: "openai",
    baseUrl: "https://api.together.xyz/v1",
    env: ["TOGETHER_API_KEY"],
    model: "moonshotai/Kimi-K2.5",
  },
  cerebras: {
    label: "Cerebras",
    protocol: "openai",
    baseUrl: "https://api.cerebras.ai/v1",
    env: ["CEREBRAS_API_KEY"],
    model: "gpt-oss-120b",
  },
  ollama: {
    label: "Ollama (local)",
    protocol: "ollama",
    baseUrl: "http://127.0.0.1:11434",
    env: [],
    model: "qwen3:8b",
    noKey: true,
  },
  custom: {
    label: "Custom OpenAI-compatible",
    protocol: "openai",
    baseUrl: "",
    env: ["LOLM_PROVIDER_API_KEY"],
    model: "",
  },
});

const ALIASES = Object.freeze({ gemini: "google", claude: "anthropic", grok: "xai", local: "ollama" });

export function normalizeProvider(value) {
  const key = String(value || "").trim().toLowerCase();
  return ALIASES[key] || key;
}

export async function loadConfig() {
  try {
    const parsed = JSON.parse(await readFile(CONFIG_PATH, "utf8"));
    if (!parsed || typeof parsed !== "object") return {};
    for (const [provider, saved] of Object.entries(parsed.providers || {})) {
      if (saved?.apiKeyRef && !saved.apiKey) saved.apiKey = await getProviderSecret(provider, saved.apiKeyRef);
    }
    return parsed;
  } catch {
    return {};
  }
}

export async function saveConfig(config) {
  const dir = dirname(CONFIG_PATH);
  await mkdir(dir, { recursive: true, mode: 0o700 });
  const temp = `${CONFIG_PATH}.${process.pid}.tmp`;
  const persisted = structuredClone(config);
  for (const saved of Object.values(persisted.providers || {})) if (saved?.apiKeyRef) delete saved.apiKey;
  await writeFile(temp, `${JSON.stringify(persisted, null, 2)}\n`, { mode: 0o600 });
  await rename(temp, CONFIG_PATH);
  await chmod(CONFIG_PATH, 0o600).catch(() => {});
}

export function envKeyFor(providerName) {
  const provider = PROVIDERS[normalizeProvider(providerName)];
  if (!provider) return { value: "", name: "" };
  for (const name of provider.env || []) {
    if (process.env[name]) return { value: process.env[name], name };
  }
  return { value: "", name: provider.env?.[0] || "" };
}

export function configuredProvider(config = {}) {
  const selected = normalizeProvider(process.env.LOLM_PROVIDER || config.provider);
  if (selected && PROVIDERS[selected]) return selected;
  for (const name of Object.keys(PROVIDERS)) {
    if (name !== "custom" && envKeyFor(name).value) return name;
  }
  return "ollama";
}

export function resolveRuntime(config = {}, flags = {}) {
  const providerName = normalizeProvider(flags.provider || configuredProvider(config));
  const provider = PROVIDERS[providerName];
  if (!provider) {
    throw new Error(`Unknown provider '${providerName}'. Run 'lolm providers' to list supported providers.`);
  }
  const saved = config.providers?.[providerName] || {};
  const envKey = envKeyFor(providerName);
  const apiKey = flags.apiKey || envKey.value || saved.apiKey || "";
  const keySource = flags.apiKey ? "flag" : envKey.value ? `env:${envKey.name}` : saved.apiKey && saved.apiKeyRef ? "secret-store" : saved.apiKey ? "config" : provider.noKey ? "not-required" : "missing";
  const baseUrl = String(flags.baseUrl || saved.baseUrl || provider.baseUrl || "").replace(/\/+$/, "");
  const model = String(flags.model || process.env.LOLM_MODEL || saved.model || provider.model || "");
  if (!baseUrl) throw new Error(`${provider.label} needs a base URL. Set it with 'lolm config set base-url URL'.`);
  if (!model) throw new Error(`${provider.label} needs a model. Set it with 'lolm config set model MODEL'.`);
  return {
    provider: providerName,
    label: provider.label,
    protocol: saved.protocol || provider.protocol,
    baseUrl,
    model,
    apiKey,
    keySource,
    keyRequired: !provider.noKey,
    // For streaming local models this is an inactivity timeout, not a total
    // generation deadline. A large local model may work for several minutes as
    // long as it keeps producing data.
    timeoutMs: Number(flags.timeout || config.timeoutMs || (providerName === "ollama" ? 600_000 : 120_000)),
  };
}

export function publicRuntime(runtime) {
  return {
    provider: runtime.provider,
    label: runtime.label,
    protocol: runtime.protocol,
    baseUrl: runtime.baseUrl,
    model: runtime.model,
    key_source: runtime.keySource,
    key_available: Boolean(runtime.apiKey) || !runtime.keyRequired,
  };
}

export function redact(value) {
  const text = String(value || "");
  if (!text) return "";
  return text.length < 9 ? "••••" : `${text.slice(0, 3)}…${text.slice(-4)}`;
}
