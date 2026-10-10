import test from "node:test";
import assert from "node:assert/strict";
import {
  renderHome,
  renderModels,
  renderActivity,
  renderSettings,
  homePresentation,
  escapeHtml,
  renderLibrary,
} from "./desktopViews.js";
import { renderStartup, renderGpu, renderAdmission } from "./settingViews.js";
import { renderActivityList } from "./activityView.js";
import { renderHomeResults } from "./homeResults.js";
const ready = {
  paired: true,
  runtimeAvailable: true,
  verified: true,
  listening: true,
};
test("Home represents every execution source and prioritizes connection recovery over pause", () => {
  assert.equal(homePresentation(ready).title, "Ready");
  assert.equal(
    homePresentation({ ...ready, admissionError: true }).target,
    "pause-retry",
  );
  for (const patch of [{ running: true }, { privateRunning: true }])
    assert.equal(homePresentation({ ...ready, ...patch }).title, "Running");
  assert.equal(homePresentation({ ...ready, paused: true }).target, "resume");
  assert.equal(
    homePresentation({ ...ready, paused: true, authFailure: true }).target,
    "connect",
  );
  assert.equal(
    homePresentation({ ...ready, failed: true, hasRun: false }).target,
    "settings",
  );
  assert.equal(
    homePresentation({ ...ready, failed: true, hasRun: true }).target,
    "run",
  );
  assert.equal(
    homePresentation({ ...ready, privateFailed: true }).title,
    "Needs attention",
  );
  assert.equal(
    homePresentation({ ...ready, privateFailed: true }).target,
    "run",
  );
  assert.match(renderHome(ready), /Choose a benchmark in Hub/);
  assert.doesNotMatch(
    renderHome(ready),
    /admission|placement|residency|sidecar/i,
  );
});
test("Models renders a combined paged library and preserves ownership actions", () => {
  const html = renderModels({
    library: {
      found: [
        {
          name: "External <model>",
          path: "/a.gguf",
          size_bytes: 1024,
          source: "LM Studio",
        },
      ],
      downloads: [
        {
          name: "Downloaded",
          managed: true,
          artifact_id: "artifact_1",
          size_bytes: 2048,
          keep: true,
        },
      ],
    },
  });
  assert.match(html, /External &lt;model&gt;/);
  assert.match(html, /LM Studio/);
  assert.match(html, /data-library-keep="artifact_1"/);
  assert.match(html, /data-library-delete="artifact_1" disabled/);
  assert.match(html, /Last used unavailable/);
  assert.match(html, /Check a model offline/);
  assert.match(html, /Chat & reasoning/);
  assert.match(html, /data-observed-runtime-start/);
  assert.match(
    renderLibrary({
      found: Array.from({ length: 6 }, (_, i) => ({
        name: "file" + i,
        path: "/a" + i + ".gguf",
      })),
    }),
    /Page 1 of 2/,
  );
});
test("Settings composes confirmed controller state and keeps advanced commands within one disclosure", () => {
  const html = renderSettings({
    components: {
      startup: {
        state: { state: { enabled: true, available: true } },
        render: renderStartup,
      },
    },
  });
  assert.match(html, /Open Runner at login" checked/);
  assert.match(html, /data-runtime-select-existing/);
  assert.match(html, /data-runner-self-test/);
  assert.match(html, /data-copy-support-summary/);
  assert.match(html, /data-install-update/);
  assert.match(html, /data-theme-choice="system"/);
  assert.doesNotMatch(html, /Refresh/);
  assert.match(
    renderStartup({ state: { enabled: true, available: true }, pending: true }),
    /checked disabled/,
  );
  assert.match(
    renderAdmission({ paused: null, error: "Read failed" }),
    /data-retry/,
  );
  const gpu = renderGpu({
    saved: {
      available: true,
      devices: [
        { index: 0, uuid: "GPU-a", selected: false },
        { index: 1, uuid: "GPU-b", selected: true },
      ],
    },
  });
  assert.match(gpu, /GPU 0/);
  assert.match(gpu, /GPU 1/);
  assert.match(gpu, /Both/);
});
test("Activity renders queue, history, use case, time, scoped results and per-run log handoff", () => {
  const activity = {
    key: "machine",
    payload: {
      runs: [
        {
          run_id: "run_1",
          status: "completed",
          model: "Qwen",
          use_case: "general_assistant",
          created_at: "2026-10-10T12:00:00Z",
        },
      ],
    },
    results: {
      run_1: {
        results: [
          {
            result_id: "r1",
            title: "Measured",
            deployment_profile: "Local",
            kind: "compare_context",
            score: 0.5,
            seconds_per_task: 2,
            qualified_count: 2,
            attempted_count: 4,
          },
        ],
      },
    },
  };
  const html = renderActivity({
    components: { activity: { state: activity, render: renderActivityList } },
  });
  assert.match(html, /Chat &amp; reasoning/);
  assert.match(html, /Run details & logs/);
  assert.match(html, /50.0 \/ 100 · 2.00 s\/task/);
  assert.match(html, /Context only/);
  assert.doesNotMatch(renderActivityList({ ...activity, key: "" }), /Qwen/);
});
test("Home results preserve report/context boundaries and escape external strings", () => {
  assert.equal(escapeHtml('<script>"&'), "&lt;script&gt;&quot;&amp;");
  const html = renderHomeResults({
    runId: "run",
    connected: true,
    data: {
      results: [
        {
          result_id: "r",
          title: "<img>",
          deployment_profile: "Local",
          kind: "report",
        },
      ],
    },
  });
  assert.match(html, /&lt;img&gt;/);
  assert.match(html, /Compare qualification unavailable/);
  assert.doesNotMatch(html, /s\/task/);
});

test("Private reports keep partial coverage and execution failures visible", async () => {
  const { renderPrivateHistory, renderPrivateEditor, renderPrivateRunning } =
    await import("./privateBenchmark.js");
  const html = renderPrivateHistory({
    rows: [
      {
        id: "report-a",
        model_filename: "<local>",
        status: "completed",
        capability_status: "partial",
        tier: "canary",
        created_at: "2026-10-10",
        component_scores: { ifeval: 0.8 },
        report_available: true,
      },
    ],
  });
  assert.match(html, /Finished · partial checks/);
  assert.match(html, /Headline score unavailable/);
  assert.match(html, /&lt;local&gt;/);
  assert.match(html, /data-open-private-report="report-a"/);
  assert.match(
    renderPrivateEditor({
      path: "/model.gguf",
      current: { status: "running" },
    }),
    /data-private-start disabled/,
  );
  assert.match(
    renderPrivateRunning({
      current: { status: "failed", phase: "Model failed to load" },
    }),
    /Model failed to load/,
  );
});
test("Token state renders failure retry and never serializes credentials", async () => {
  const { renderHf } = await import("./hfCredentials.js");
  assert.match(renderHf({ state: { saved: true } }), /Remove token/);
  assert.match(renderHf({ error: "Read failed" }), /data-hf-retry /);
  assert.doesNotMatch(
    renderHf({ state: { saved: true, token: "sensitive-value" } }),
    /sensitive-value/,
  );
});
