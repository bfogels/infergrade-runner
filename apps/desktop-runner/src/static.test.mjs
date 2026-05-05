import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("desktop shell permission shapes keep version separate from URL-scoped commands", () => {
  const capability = JSON.parse(
    readFileSync(new URL("../src-tauri/capabilities/default.json", import.meta.url), "utf8")
  );
  const permissions = capability.permissions.flatMap((permission) => permission.allow || []);
  const shapes = permissions.map((entry) => JSON.stringify(entry.args || []));

  assert.ok(shapes.includes(JSON.stringify(["--version"])));
  assert.ok(shapes.includes(JSON.stringify(["desktop-self-test"])));
  assert.ok(shapes.some((shape) => shape.includes('"start"') && shape.includes('"--api-url"')));
  assert.ok(shapes.some((shape) => shape.includes('"pair"') && shape.includes('"--api-url"')));
  assert.ok(shapes.some((shape) => shape.includes('"install-runtime"') && !shape.includes('"--api-url"')));
});

test("desktop onboarding exposes paste-code pairing, reset, and bundled runner self-test", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");

  assert.ok(html.includes('value="https://api.infergrade.com"'));
  assert.ok(html.includes("Paste the one-time code from Hub"));
  assert.ok(html.includes("data-reset-pairing"));
  assert.ok(html.includes("data-runner-self-test"));
  assert.ok(js.includes("normalizeDesktopApiUrl"));
  assert.ok(js.includes("desktop-self-test"));
});
