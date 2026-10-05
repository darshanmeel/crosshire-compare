// web/scripts/source-hash.mjs - the hash tests/test_web_build.py recomputes in Python
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = fileURLToPath(new URL("..", import.meta.url));
const TOP = ["index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"];
// src/ is what git tracks, so a scratch file or an editor backup there cannot change the hash
const tracked = execFileSync("git", ["ls-files", "-z", "--", "src"], { cwd: WEB, encoding: "utf8" }).split("\0").filter(Boolean);
const files = [...TOP, ...tracked].sort();
const h = createHash("sha256");
for (const f of files) {
  h.update(f + "\n");
  h.update(readFileSync(join(WEB, f), "utf8").replace(/\r\n/g, "\n"));
  h.update("\n");
}
writeFileSync(join(WEB, "..", "tablecmp", "web_dist", "source-hash.txt"), h.digest("hex") + "\n");
