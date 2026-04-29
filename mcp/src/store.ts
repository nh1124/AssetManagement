// ============================================================
// JSON File-Based Data Store
// ============================================================

import { readFileSync, writeFileSync, existsSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import type { Portfolio, Budget, DecisionLog } from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = join(__dirname, "..", "data");

function readJson<T>(filename: string): T {
  const filepath = join(DATA_DIR, filename);
  if (!existsSync(filepath)) {
    throw new Error(`Data file not found: ${filepath}`);
  }
  const raw = readFileSync(filepath, "utf-8");
  return JSON.parse(raw) as T;
}

function writeJson<T>(filename: string, data: T): void {
  const filepath = join(DATA_DIR, filename);
  writeFileSync(filepath, JSON.stringify(data, null, 2), "utf-8");
}

// Portfolio
export function getPortfolio(): Portfolio {
  return readJson<Portfolio>("portfolio.json");
}

export function savePortfolio(portfolio: Portfolio): void {
  portfolio.as_of = new Date().toISOString().split("T")[0];
  writeJson("portfolio.json", portfolio);
}

// Budget
export function getBudget(): Budget {
  return readJson<Budget>("budget.json");
}

export function saveBudget(budget: Budget): void {
  budget.as_of = new Date().toISOString().split("T")[0];
  writeJson("budget.json", budget);
}

// Decision Log
export function getDecisionLog(): DecisionLog {
  return readJson<DecisionLog>("decisions.json");
}

export function saveDecisionLog(log: DecisionLog): void {
  writeJson("decisions.json", log);
}
