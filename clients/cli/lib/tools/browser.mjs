// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { randomUUID } from "node:crypto";
import { commandResult, objectSchema, resolveUserPath, runFile, truncate } from "./shared.mjs";

async function playwright() {
  try { return await import("playwright-core"); }
  catch (error) {
    throw Object.assign(new Error("Browser automation needs playwright-core. Reinstall or update lolm-cli, then run `lolm doctor`."), { code: "PLAYWRIGHT_MISSING", cause: error });
  }
}

export class BrowserManager {
  constructor({ root }) {
    this.root = root;
    this.browser = null;
    this.context = null;
    this.page = null;
  }

  async start({ cdp_url, headless = false } = {}) {
    if (this.browser?.isConnected()) return this.snapshot();
    const { chromium } = await playwright();
    if (cdp_url) {
      this.browser = await chromium.connectOverCDP(cdp_url);
      this.context = this.browser.contexts()[0] || await this.browser.newContext();
    } else {
      try { this.browser = await chromium.launch({ channel: "chrome", headless }); }
      catch { this.browser = await chromium.launch({ headless }); }
      this.context = await this.browser.newContext({ viewport: { width: 1440, height: 900 } });
    }
    this.page = this.context.pages()[0] || await this.context.newPage();
    return this.snapshot();
  }

  async ensure(options = {}) {
    if (!this.browser?.isConnected()) await this.start(options);
    if (!this.page || this.page.isClosed()) this.page = this.context.pages()[0] || await this.context.newPage();
    return this.page;
  }

  async snapshot() {
    if (!this.page) return { connected: false };
    return { connected: true, url: this.page.url(), title: await this.page.title().catch(() => ""), pages: this.context?.pages().length || 0 };
  }

  async open(url, options = {}) {
    const page = await this.ensure(options); const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: options.timeout_ms || 30_000 });
    return { ...(await this.snapshot()), status: response?.status() || null };
  }

  async inspect({ selector = "body", max_chars = 30_000 } = {}) {
    const page = await this.ensure();
    const locator = page.locator(selector).first();
    const text = await locator.innerText({ timeout: 10_000 });
    const html = await locator.evaluate((element) => element.outerHTML.slice(0, 50_000));
    return { ...(await this.snapshot()), selector, text: truncate(text, max_chars), html: truncate(html, max_chars) };
  }

  async click({ selector, text, button = "left" }) {
    const page = await this.ensure();
    const locator = selector ? page.locator(selector).first() : page.getByText(text, { exact: false }).first();
    await locator.click({ button, timeout: 15_000 });
    return this.snapshot();
  }

  async type({ selector, text, clear = true, press }) {
    const page = await this.ensure(); const locator = page.locator(selector).first();
    if (clear) await locator.fill(text); else await locator.type(text);
    if (press) await locator.press(press);
    return this.snapshot();
  }

  async screenshot(value) {
    const page = await this.ensure();
    const path = value ? resolveUserPath(this.root, value) : join(this.root, ".lolm", "screenshots", `${Date.now()}-${randomUUID().slice(0, 6)}.png`);
    await mkdir(dirname(path), { recursive: true });
    await page.screenshot({ path, fullPage: true });
    return { path, ...(await this.snapshot()) };
  }

  async tabs() {
    if (!this.context) return { tabs: [] };
    const tabs = await Promise.all(this.context.pages().map(async (page, index) => ({ index, url: page.url(), title: await page.title().catch(() => ""), active: page === this.page })));
    return { tabs };
  }

  async select(index) {
    if (!this.context?.pages()[index]) throw Object.assign(new Error(`Unknown browser tab: ${index}`), { code: "UNKNOWN_TAB" });
    this.page = this.context.pages()[index]; await this.page.bringToFront(); return this.snapshot();
  }

  async close() {
    if (this.browser) await this.browser.close();
    this.browser = this.context = this.page = null;
    return { connected: false };
  }
}

export function registerBrowserTools(registry, { browser }) {
  registry.register({
    name: "browser.start", description: "Start a persistent Chrome automation session or connect to a user-approved CDP endpoint.", risk: "execute", approval: "confirm",
    inputSchema: objectSchema({ cdp_url: { type: "string" }, headless: { type: "boolean" } }), execute: async (args) => browser.start(args),
  });
  registry.register({
    name: "browser.open", description: "Navigate the persistent browser session to a URL.", risk: "external", approval: "confirm",
    inputSchema: objectSchema({ url: { type: "string", minLength: 1 }, headless: { type: "boolean" }, timeout_ms: { type: "integer", minimum: 1000, maximum: 120_000 } }, ["url"]), execute: async ({ url, ...options }) => browser.open(url, options),
  });
  registry.register({
    name: "browser.inspect", description: "Read the visible text and bounded HTML for a page or selector.", risk: "read",
    inputSchema: objectSchema({ selector: { type: "string" }, max_chars: { type: "integer", minimum: 100, maximum: 50_000 } }), execute: async (args) => browser.inspect(args),
  });
  registry.register({
    name: "browser.click", description: "Click an element by CSS selector or visible text.", risk: "external", approval: "confirm",
    inputSchema: { type: "object", oneOf: [objectSchema({ selector: { type: "string", minLength: 1 }, button: { type: "string", enum: ["left", "right", "middle"] } }, ["selector"]), objectSchema({ text: { type: "string", minLength: 1 }, button: { type: "string", enum: ["left", "right", "middle"] } }, ["text"])] }, execute: async (args) => browser.click(args),
  });
  registry.register({
    name: "browser.type", description: "Type into a browser field and optionally press a key.", risk: "external", approval: "confirm",
    inputSchema: objectSchema({ selector: { type: "string", minLength: 1 }, text: { type: "string" }, clear: { type: "boolean" }, press: { type: "string" } }, ["selector", "text"]), execute: async (args) => browser.type(args),
  });
  registry.register({
    name: "browser.screenshot", description: "Capture the current full browser page to a local PNG.", risk: "write", approval: "confirm",
    inputSchema: objectSchema({ path: { type: "string" } }), execute: async ({ path }) => browser.screenshot(path),
  });
  registry.register({ name: "browser.tabs", description: "List tabs in the persistent browser session.", risk: "read", inputSchema: objectSchema(), execute: async () => browser.tabs() });
  registry.register({ name: "browser.selectTab", description: "Select and focus a browser tab by index.", risk: "external", approval: "confirm", inputSchema: objectSchema({ index: { type: "integer", minimum: 0 } }, ["index"]), execute: async ({ index }) => browser.select(index) });
  registry.register({ name: "browser.close", description: "Close the browser automation session.", risk: "execute", approval: "auto", inputSchema: objectSchema(), execute: async () => browser.close() });
}

export function registerComputerTools(registry, { browser }) {
  const desktopOnly = () => { if (process.platform !== "darwin") throw Object.assign(new Error("Desktop computer-use fallback currently requires macOS; use browser.* for portable web automation."), { code: "DESKTOP_AUTOMATION_UNAVAILABLE" }); };
  const desktopScreenshot = async (value) => {
    desktopOnly(); const path = value ? resolveUserPath(browser.root, value) : join(browser.root, ".lolm", "screenshots", `desktop-${Date.now()}.png`);
    await mkdir(dirname(path), { recursive: true }); commandResult(await runFile("screencapture", ["-x", path], { timeoutMs: 20_000 }), "desktop screenshot"); return { target: "desktop", path };
  };
  registry.register({
    name: "computer.observe", description: "Observe the browser as structured text, or capture the active macOS desktop when Playwright cannot reach the UI.", risk: "read",
    classify: ({ target = "auto" }) => target === "desktop" || (target === "auto" && !browser.page) ? { risk: "write", approval: "confirm", reason: "Desktop observation captures a screenshot and may require macOS Screen Recording permission." } : { risk: "read", approval: "auto" },
    inputSchema: objectSchema({ target: { type: "string", enum: ["auto", "browser", "desktop"] }, max_chars: { type: "integer", minimum: 100, maximum: 50_000 }, path: { type: "string" } }),
    execute: async ({ target = "auto", max_chars, path }) => {
      if (target !== "desktop" && browser.page) return browser.inspect({ max_chars });
      desktopOnly(); const active = await runFile("osascript", ["-e", "tell application \"System Events\" to get name of first application process whose frontmost is true"], { timeoutMs: 10_000 });
      return { ...(await desktopScreenshot(path)), active_application: active.ok ? active.stdout.trim() : null, note: "Use the screenshot as visual evidence; macOS may request Screen Recording permission." };
    },
  });
  registry.register({
    name: "computer.click", description: "Click browser content by selector/text, or use an approved macOS coordinate click when Playwright is insufficient.", risk: "external", approval: "confirm",
    inputSchema: { type: "object", oneOf: [objectSchema({ selector: { type: "string", minLength: 1 }, target: { type: "string", enum: ["browser"] } }, ["selector"]), objectSchema({ text: { type: "string", minLength: 1 }, target: { type: "string", enum: ["browser"] } }, ["text"]), objectSchema({ x: { type: "integer", minimum: 0 }, y: { type: "integer", minimum: 0 }, target: { type: "string", enum: ["desktop"] } }, ["x", "y"])] },
    execute: async ({ x, y, ...args }) => { if (Number.isInteger(x) && Number.isInteger(y)) { desktopOnly(); commandResult(await runFile("osascript", ["-e", `tell application \"System Events\" to click at {${x}, ${y}}`], { timeoutMs: 10_000 }), "desktop click"); return { target: "desktop", x, y }; } return browser.click(args); },
  });
  registry.register({
    name: "computer.type", description: "Type into a browser selector, or send approved text to the active macOS application when Playwright is insufficient.", risk: "external", approval: "confirm",
    inputSchema: objectSchema({ target: { type: "string", enum: ["browser", "desktop"] }, selector: { type: "string" }, text: { type: "string" }, clear: { type: "boolean" }, press: { type: "string" } }, ["text"]),
    execute: async ({ target = "browser", selector, text, clear, press }) => {
      if (target !== "desktop") { if (!selector) throw Object.assign(new Error("Browser typing requires selector."), { code: "INVALID_TOOL_ARGUMENTS" }); return browser.type({ selector, text, clear, press }); }
      desktopOnly(); const script = "on run argv\ntell application \"System Events\" to keystroke (item 1 of argv)\nend run";
      commandResult(await runFile("osascript", ["-e", script, "--", text], { timeoutMs: 10_000 }), "desktop typing"); return { target: "desktop", characters: text.length };
    },
  });
  registry.register({
    name: "computer.screenshot", description: "Capture the browser page or active macOS desktop as a local PNG artifact.", risk: "write", approval: "confirm",
    inputSchema: objectSchema({ target: { type: "string", enum: ["auto", "browser", "desktop"] }, path: { type: "string" } }),
    execute: async ({ target = "auto", path }) => target !== "desktop" && browser.page ? browser.screenshot(path) : desktopScreenshot(path),
  });
}
