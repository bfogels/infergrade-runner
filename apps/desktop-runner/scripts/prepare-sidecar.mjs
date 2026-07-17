import { spawnSync } from "node:child_process";
import { chmodSync, copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const rootDir = resolve(appDir, "../..");
const sidecarManifest = resolve(appDir, "sidecar/Cargo.toml");
const targetTriple = process.env.INFERGRADE_DESKTOP_SIDECAR_TARGET || rustHostTriple();
const exeSuffix = targetTriple.includes("windows") ? ".exe" : "";
const cargoArgs = ["build", "--manifest-path", sidecarManifest, "--release", "--locked"];
if (process.env.INFERGRADE_DESKTOP_SIDECAR_TARGET) {
  cargoArgs.push("--target", targetTriple);
}
run("cargo", cargoArgs, "build the InferGrade desktop sidecar");

const targetParts = process.env.INFERGRADE_DESKTOP_SIDECAR_TARGET
  ? [rootDir, "target", targetTriple, "release"]
  : [rootDir, "target", "release"];
const builtBinary = resolve(...targetParts, `infergrade-sidecar${exeSuffix}`);
const outputBinary = resolve(appDir, "src-tauri/binaries", `infergrade-sidecar-${targetTriple}${exeSuffix}`);
mkdirSync(dirname(outputBinary), { recursive: true });
copyFileSync(builtBinary, outputBinary);
if (!exeSuffix) {
  chmodSync(outputBinary, 0o755);
}
console.log(`desktop_runner_sidecar=${outputBinary}`);

function rustHostTriple() {
  const result = spawnSync("rustc", ["-Vv"], { encoding: "utf8" });
  if (result.error || result.status !== 0) {
    console.error("Could not resolve the Rust host target. Install Rust before running Tauri.");
    process.exit(1);
  }
  const match = String(result.stdout || "").match(/^host:\s*(\S+)$/m);
  if (!match) {
    console.error("rustc -Vv did not report a host target triple.");
    process.exit(1);
  }
  return match[1];
}

function run(command, args, purpose) {
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.error || result.status !== 0) {
    console.error(`Could not ${purpose}${result.error ? `: ${result.error.message}` : "."}`);
    process.exit(result.status || 1);
  }
}
