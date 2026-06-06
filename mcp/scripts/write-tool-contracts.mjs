import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const rootDir = path.resolve(import.meta.dirname, "..");
const contractPath = path.join(rootDir, "contracts", "write-tools.json");
const contracts = JSON.parse(fs.readFileSync(contractPath, "utf8"));

let failures = 0;
for (const contract of contracts) {
  const sourcePath = path.join(rootDir, contract.source);
  if (!fs.existsSync(sourcePath)) {
    console.error(`[missing-source] ${contract.tool}: ${contract.source}`);
    failures += 1;
    continue;
  }

  const source = fs.readFileSync(sourcePath, "utf8");
  const checks = [
    [`tool`, `"${contract.tool}"`],
    [`method`, `api.${contract.method}`],
    [`path`, contract.path_fragment],
  ];

  for (const [label, needle] of checks) {
    if (!source.includes(needle)) {
      console.error(`[missing-${label}] ${contract.tool}: expected ${JSON.stringify(needle)} in ${contract.source}`);
      failures += 1;
    }
  }
}

const tools = new Set(contracts.map((contract) => contract.tool));
const endpoints = new Set(contracts.map((contract) => `${contract.method.toUpperCase()} ${contract.path}`));
console.log(`write tool contracts: ${contracts.length} entries, ${tools.size} tools, ${endpoints.size} endpoints`);

if (failures > 0) {
  console.error(`write tool contract check failed: ${failures} issue(s)`);
  process.exit(1);
}
