#!/usr/bin/env node
/**
 * Flags packages sitting in node_modules that the lockfile does not account for.
 *
 * Why this exists: on 2026-07-12 a recursive copy that followed another repo's
 * npm workspace junctions dumped four foreign packages here, one of which
 * carried a 20GB Rust build directory. Nothing noticed for three months --
 * node_modules is gitignored and dockerignored, so the only symptom was disk
 * use. `npm ci` wipes node_modules and would have cleared it; `npm install`
 * leaves unknown directories alone.
 *
 * Exits non-zero when it finds something unexpected.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const modulesDir = join(root, "node_modules");

let lock;
try {
  lock = JSON.parse(readFileSync(join(root, "package-lock.json"), "utf8"));
} catch {
  console.error("package-lock.json is missing or unreadable; run npm install first.");
  process.exit(1);
}

let entries;
try {
  entries = readdirSync(modulesDir, { withFileTypes: true });
} catch {
  console.log("node_modules is absent -- nothing to check.");
  process.exit(0);
}

// Every package the lockfile installs appears as a "node_modules/<name>" key.
const expected = new Set(
  Object.keys(lock.packages ?? {})
    .filter((p) => p.startsWith("node_modules/"))
    .map((p) => p.slice("node_modules/".length).split("/node_modules/").pop())
    .map((p) => (p.startsWith("@") ? p.split("/").slice(0, 2).join("/") : p.split("/")[0])),
);

const unexpected = [];
for (const entry of entries) {
  if (!entry.isDirectory() || entry.name.startsWith(".")) continue;

  if (entry.name.startsWith("@")) {
    // Scoped: check each package inside the scope.
    for (const scoped of readdirSync(join(modulesDir, entry.name), { withFileTypes: true })) {
      if (!scoped.isDirectory()) continue;
      const name = `${entry.name}/${scoped.name}`;
      if (!expected.has(name)) unexpected.push(name);
    }
    continue;
  }

  if (!expected.has(entry.name)) unexpected.push(entry.name);
}

if (unexpected.length === 0) {
  console.log(`node_modules is clean (${expected.size} packages accounted for).`);
  process.exit(0);
}

console.error("Packages in node_modules that the lockfile does not list:\n");
for (const name of unexpected.sort()) {
  let size = "";
  try {
    // Only stat the top level; walking a stray 20GB tree defeats the purpose.
    size = statSync(join(modulesDir, name)).isDirectory() ? " (directory)" : "";
  } catch {
    /* ignore */
  }
  console.error(`  ${name}${size}`);
}
console.error(
  "\nThese were not installed from package.json. The usual cause is a recursive copy" +
    "\nthat followed another project's workspace links. Remove them, or re-create the" +
    "\ntree with `npm ci`, which deletes node_modules before installing.",
);
process.exit(1);
