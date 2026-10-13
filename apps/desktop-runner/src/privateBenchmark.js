import { setPageState } from "./desktopState.js";
import { renderPageComponent } from "./desktopNavigation.js";
import { escapeHtml as e } from "./desktopViews.js";
const componentLabels = {
  ifeval: "IFEval",
  assistant_compositional_instruction_v2: "Compositional instructions",
  multiturn_chat_memory_v1: "Chat memory",
  coding_static_repair_v1: "Static code repair",
  reasoning_exact_answer_v1: "Exact reasoning answers",
};
export function createPrivateBenchmarkController({
  start,
  stop,
  status,
  history,
  openReport,
  render,
}) {
  let current = { status: "idle", pid: null },
    rows = [],
    pending = false,
    error = null,
    generation = 0,
    reading = false,
    historyPending = false,
    historySequence = 0;
  const show = () => render({ current, rows, pending, historyPending, error });
  const refreshHistory = async () => {
    if (current.status === "running" || historyPending) return;
    const own = generation,
      sequence = ++historySequence;
    historyPending = true;
    show();
    try {
      const value = await history();
      if (own !== generation || sequence !== historySequence) return;
      if (
        value?.schema_version !== "infergrade.private_history.v1" ||
        !Array.isArray(value.results)
      )
        throw new Error();
      rows = value.results;
      error = value.unreadable_count
        ? "Some local reports could not be read. Check local storage."
        : null;
    } catch {
      if (own === generation && sequence === historySequence)
        error =
          "Could not read private history. Refresh after checking local storage.";
    } finally {
      if (sequence === historySequence) {
        historyPending = false;
        show();
      }
    }
  };
  const refresh = async () => {
    if (reading) return;
    reading = true;
    const own = generation;
    try {
      const value = await status();
      if (!["idle", "running", "completed", "failed"].includes(value?.status))
        throw new Error();
      if (own !== generation) return;
      const was = current.status;
      current = value;
      if (value.status !== "running" && was !== value.status)
        await refreshHistory();
      show();
    } catch {
      if (own === generation) {
        error = "Could not confirm private work. Keep Runner open and refresh.";
        show();
      }
    } finally {
      reading = false;
    }
  };
  return {
    refresh,
    refreshHistory,
    repaint: show,
    isRunning: () => ["running", "unconfirmed"].includes(current.status),
    start: async (input) => {
      if (pending || ["running", "unconfirmed"].includes(current.status))
        return false;
      let started = false;
      pending = true;
      error = null;
      ++generation;
      show();
      try {
        const value = await start(input);
        if (value?.status !== "running" || !Number.isInteger(value.pid))
          throw new Error(
            "Private benchmark did not return a process identity.",
          );
        current = value;
        started = true;
      } catch (e) {
        error =
          typeof e === "string"
            ? e
            : e?.message ||
              "Could not start a private benchmark. Check the installed runtime and stop listening.";
        try {
          const confirmed = await status();
          if (
            !["idle", "running", "completed", "failed"].includes(
              confirmed?.status,
            )
          )
            throw new Error();
          current = confirmed;
          if (confirmed.status === "running") {
            started = true;
            error = null;
          }
        } catch {
          current = {
            status: "unconfirmed",
            pid: null,
            phase:
              "Confirm whether private work started. Keep Runner open and refresh.",
          };
        }
      } finally {
        pending = false;
        show();
      }
      return started;
    },
    stop: async () => {
      if (
        pending ||
        current.status !== "running" ||
        !Number.isInteger(current.pid)
      )
        return;
      pending = true;
      error = null;
      show();
      try {
        await stop(current.pid);
        current = {
          ...current,
          phase: "Stop requested. Waiting for process cleanup.",
        };
      } catch {
        error = "Could not request Stop. Keep Runner open and try again.";
      } finally {
        pending = false;
        show();
      }
    },
    openReport: async (id) => {
      try {
        await openReport(id);
      } catch {
        error = "Could not open the local report. Refresh private history.";
        show();
      }
    },
  };
}
export function renderPrivateEditor({
  path = "",
  current = {},
  pending,
  historyPending,
  error,
} = {}) {
  const busy =
    pending ||
    historyPending ||
    ["running", "unconfirmed"].includes(current.status);
  return `<h2 tabindex="-1">Benchmark a local file privately</h2><p>The report stays on this machine; stop listening before starting.</p><label>Local GGUF file<input data-private-path value="${e(path)}" placeholder="Choose a file from the library"></label><label hidden>Use case<select data-private-use-case><option value="general_assistant">Chat & reasoning</option><option value="agentic_coding">Coding</option><option value="reasoning">Reasoning</option></select></label><label title="Small samples cover fewer tasks; reports show missing coverage and runtime compatibility checks.">Depth<select data-private-tier><option value="canary">Canary · small sample</option><option value="standard">Standard · larger sample</option></select></label><button type="button" data-private-start ${busy || !path ? "disabled" : ""}>Start private benchmark</button><p data-private-error role="status" ${error ? "" : "hidden"}>${e(error)}</p>`;
}
export function renderPrivateRunning({ current = {}, pending, error } = {}) {
  return `<h2>Private benchmark</h2><p role="status">${e(error || current.phase || current.status)}</p><button type="button" data-private-stop ${pending || current.status !== "running" ? "disabled" : ""}>Stop private benchmark</button><button type="button" data-private-status>Check status</button><p class="meta">Keep this machine awake; the report stays here.</p>`;
}
export function renderPrivateHistory({
  rows = [],
  historyPending,
  error,
} = {}) {
  return `<h2>Private on this machine</h2><p role="status">${e(error || (rows.length ? `${rows.length} local report${rows.length === 1 ? "" : "s"}.` : "No private benchmarks yet."))}</p>${rows
    .map((row) => {
      const status =
        row.status === "running"
          ? "Unfinished"
          : row.status === "completed"
            ? row.capability_status === "not_comparable"
              ? "Finished · diagnostics only"
              : row.capability_status === "partial"
                ? "Finished · partial checks"
                : "Finished"
            : "Did not finish";
      const parts = Object.entries(row.component_scores || {})
        .filter(([, value]) => Number.isFinite(value))
        .map(
          ([name, value]) =>
            `${componentLabels[name] || name}: ${(value * 100).toFixed(1)}%`,
        );
      const score = Number.isFinite(row.score)
        ? `Capability score ${(row.score * 100).toFixed(1)} / 100`
        : parts.length
          ? `Component results · ${parts.join(" · ")}. Headline score unavailable.`
          : "See the local report for execution details.";
      return `<div class="private-history-row" data-private-report-id="${e(row.id)}"><strong>${e(row.model_filename)}</strong><p>${e(status)} · ${row.tier === "canary" ? "Small sample" : "Standard"} · ${e(new Date(row.created_at).toLocaleString())} · private</p><p>${e(score)}</p>${row.report_available ? `<button type="button" data-open-private-report="${e(row.id)}">Open local report</button>` : ""}</div>`;
    })
    .join(
      "",
    )}<button type="button" data-private-history-refresh ${historyPending ? "disabled" : ""}>Check private history</button>`;
}
export function initPrivateBenchmark({ invoke, onRun = () => {} }) {
  const panel = document.querySelector('[data-slot="private-benchmark"]'),
    runPanel = document.querySelector('[data-slot="private-running"]'),
    historyPanel = document.querySelector('[data-slot="private-history"]');
  if (!panel || !runPanel || !historyPanel) return null;
  panel.className = "drawer-panel desktop-private-benchmark";
  runPanel.className = "drawer-panel desktop-private-running";
  historyPanel.className = "drawer-panel desktop-private-history";
  let path = "";
  const call = async (command, args) => {
    const transport = await invoke();
    if (!transport)
      throw new Error("Open the desktop app to benchmark a local file.");
    return transport(command, args);
  };
  const controller = createPrivateBenchmarkController({
    start: (args) => call("start_desktop_private_benchmark", args),
    stop: (expectedPid) =>
      call("stop_desktop_private_benchmark", { expectedPid }),
    status: () => call("desktop_private_benchmark_status"),
    history: () => call("desktop_private_benchmark_history"),
    openReport: (id) => call("open_desktop_private_report", { id }),
    render: (state) => {
      const running = ["running", "unconfirmed"].includes(state.current.status);
      document.documentElement.dataset.privateRunning = String(running);
      setPageState("home", {
        privateRunning: running,
        privateFailed: state.current.status === "failed",
      });
      renderPageComponent(
        "models",
        "private-benchmark",
        { ...state, path },
        renderPrivateEditor,
      );
      renderPageComponent(
        "home",
        "private-running",
        state,
        renderPrivateRunning,
      );
      runPanel.hidden = state.current.status === "idle";
      renderPageComponent(
        "activity",
        "private-history",
        state,
        renderPrivateHistory,
      );
    },
  });
  panel.oninput = (event) => {
    if (event.target.matches("[data-private-path]")) {
      path = event.target.value;
      controller.repaint();
    }
  };
  panel.onclick = async (event) => {
    if (!event.target.closest("[data-private-start]") || event.target.disabled)
      return;
    const started = await controller.start({
      modelPath: path,
      useCase: document.querySelector(
        '[data-check-use-case][aria-pressed="true"]',
      ).dataset.checkUseCase,
      tier: panel.querySelector("[data-private-tier]").value,
    });
    if (started) onRun();
  };
  runPanel.onclick = (event) => {
    if (event.target.closest("[data-private-stop]")) controller.stop();
    if (event.target.closest("[data-private-status]")) controller.refresh();
  };
  historyPanel.onclick = (event) => {
    const button = event.target.closest("button");
    if (button?.dataset.openPrivateReport)
      controller.openReport(button.dataset.openPrivateReport);
    if (button?.matches("[data-private-history-refresh]"))
      controller.refreshHistory();
  };
  controller.refresh().then(() => controller.refreshHistory());
  window.setInterval(() => {
    if (controller.isRunning()) controller.refresh();
  }, 1500);
  return {
    chooseFile: (value) => {
      path = value;
      controller.repaint();
      panel.querySelector("[data-private-path]").value = value;
      panel.querySelector("h2").focus();
      panel.scrollIntoView({ block: "start" });
    },
    controller,
  };
}
