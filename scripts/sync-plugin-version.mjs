#!/usr/bin/env node
// Copy the version from package.json (which Changesets bumps) into both Claude Code plugin manifests.
// usage: node scripts/sync-plugin-version.mjs
import { readFileSync, writeFileSync } from "node:fs";

const root = new URL("..", import.meta.url);
const read = (path) => JSON.parse(readFileSync(new URL(path, root), "utf8"));
const write = (path, data) => writeFileSync(new URL(path, root), `${JSON.stringify(data, null, 2)}\n`);

const { version } = read("package.json");

const plugin = read(".claude-plugin/plugin.json");
plugin.version = version;
write(".claude-plugin/plugin.json", plugin);

const marketplace = read(".claude-plugin/marketplace.json");
marketplace.metadata.version = version;
write(".claude-plugin/marketplace.json", marketplace);

console.log(`plugin manifests set to ${version}`);
