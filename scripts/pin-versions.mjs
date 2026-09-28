#!/usr/bin/env node
// Replace "latest" ranges in workspace package.json files with the exact installed
// version (as ^x.y.z), so the repo never floats on "latest" after first install.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const workspaces = ["apps/web", "packages/api-client", "packages/design-tokens"];

let changed = 0;
for (const ws of workspaces) {
  const pkgPath = join(root, ws, "package.json");
  const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
  const req = createRequire(pkgPath);
  for (const field of ["dependencies", "devDependencies"]) {
    for (const [name, range] of Object.entries(pkg[field] ?? {})) {
      if (range !== "latest") continue;
      const candidates = [join(root, ws, "node_modules", name, "package.json")];
      try {
        candidates.push(req.resolve(`${name}/package.json`));
      } catch {}
      const found = candidates.find((p) => existsSync(p));
      if (!found) {
        console.warn(`! ${ws}: ${name} not installed; left as latest`);
        continue;
      }
      const { version } = JSON.parse(readFileSync(found, "utf8"));
      pkg[field][name] = `^${version}`;
      changed++;
    }
  }
  writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + "\n");
}
console.log(`pinned ${changed} dependencies`);
