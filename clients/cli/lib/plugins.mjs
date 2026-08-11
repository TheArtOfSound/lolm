// Copyright (c) 2026 Bryan Leonard & Brandyn Leonard
// SPDX-License-Identifier: AGPL-3.0-or-later
import { readFile, readdir, stat } from "node:fs/promises";
import { delimiter, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { homedir } from "node:os";
import { pathToFileURL } from "node:url";

const MANIFEST = "lolm-plugin.json";

async function manifestPaths(base) {
  try {
    const info = await stat(base);
    if (info.isFile()) return [base];
    const direct = join(base, MANIFEST);
    try { await stat(direct); return [direct]; } catch {}
    const entries = await readdir(base, { withFileTypes: true });
    return entries.filter((entry) => entry.isDirectory()).map((entry) => join(base, entry.name, MANIFEST));
  } catch { return []; }
}

export class PluginManager {
  constructor({ root, registry }) {
    this.root = resolve(root);
    this.registry = registry;
    this.loaded = [];
  }

  searchPaths() {
    const explicit = String(process.env.LOLM_PLUGIN_PATH || "").split(delimiter).filter(Boolean);
    return [...explicit, join(this.root, ".lolm", "plugins"), join(homedir(), ".lolm", "plugins")];
  }

  async discover() {
    const paths = [];
    for (const base of this.searchPaths()) paths.push(...await manifestPaths(base));
    const plugins = [];
    for (const path of [...new Set(paths)]) {
      try {
        const manifest = JSON.parse(await readFile(path, "utf8"));
        plugins.push({ ...manifest, manifest_path: path, directory: dirname(path), enabled: manifest.enabled === true });
      } catch (error) { plugins.push({ manifest_path: path, enabled: false, error: error.message }); }
    }
    return plugins;
  }

  async loadEnabled() {
    const results = [];
    for (const plugin of await this.discover()) {
      if (!plugin.enabled || plugin.error) { results.push({ ...plugin, loaded: false }); continue; }
      try {
        if (!plugin.name || !plugin.version || !plugin.main) throw new Error("Manifest needs name, version, main, and enabled=true.");
        const main = resolve(plugin.directory, plugin.main);
        const escaped = relative(plugin.directory, main).startsWith("..") || isAbsolute(relative(plugin.directory, main));
        if (escaped) throw new Error("Plugin main must stay inside its plugin directory.");
        const module = await import(`${pathToFileURL(main).href}?v=${encodeURIComponent(plugin.version)}`);
        if (typeof module.register !== "function") throw new Error("Plugin main must export register(registry, context).");
        const before = new Set(this.registry.list().map((tool) => tool.name));
        await module.register(this.registry, { root: this.root, manifest: plugin });
        const tools = this.registry.list().map((tool) => tool.name).filter((name) => !before.has(name));
        const result = { name: plugin.name, version: plugin.version, manifest_path: plugin.manifest_path, loaded: true, tools };
        this.loaded.push(result); results.push(result);
      } catch (error) { results.push({ name: plugin.name, version: plugin.version, manifest_path: plugin.manifest_path, loaded: false, error: error.message }); }
    }
    return results;
  }
}
