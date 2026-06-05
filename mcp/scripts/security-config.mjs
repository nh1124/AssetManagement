import { spawnSync } from "node:child_process";

function runAuthImport(env) {
  return spawnSync(
    process.execPath,
    ["--input-type=module", "-e", "await import('./dist/auth.js')"],
    {
      cwd: process.cwd(),
      env: { ...process.env, ...env },
      encoding: "utf8",
    },
  );
}

function assertFailsWithDefaultSecret(defaultSecret) {
  const result = runAuthImport({
    APP_ENV: "production",
    JWT_SECRET: defaultSecret,
  });

  if (result.status === 0) {
    throw new Error(`Expected production import to reject default JWT_SECRET: ${defaultSecret}`);
  }
  if (!result.stderr.includes("JWT_SECRET must be changed in production")) {
    throw new Error(`Unexpected stderr for default JWT_SECRET: ${result.stderr}`);
  }
}

function assertPasses(env) {
  const result = runAuthImport(env);
  if (result.status !== 0) {
    throw new Error(`Expected auth import to pass, got ${result.status}: ${result.stderr}`);
  }
}

assertFailsWithDefaultSecret("dev-secret-change-in-production");
assertFailsWithDefaultSecret("change-me-to-a-secret-key-at-least-32-chars");
assertPasses({ APP_ENV: "development", JWT_SECRET: "dev-secret-change-in-production" });
assertPasses({ APP_ENV: "production", JWT_SECRET: "prod-secret-at-least-32-characters" });

console.log("security config ok");
