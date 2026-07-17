import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("../../../scripts/build_desktop_sidecar.sh", import.meta.url));
const command = process.platform === "win32" ? "bash" : script;
const args = process.platform === "win32" ? [script] : [];
const result = spawnSync(command, args, { stdio: "inherit" });

if (result.error) {
  console.error(`Could not prepare the InferGrade desktop sidecar: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
