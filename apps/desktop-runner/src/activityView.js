import { escapeHtml as e } from "./desktopViews.js";
import { activityGroups, activityLabels } from "./desktopActivity.js";
export function renderActivityList({
  payload,
  key,
  results = {},
  errors = {},
  error,
} = {}) {
  if (!key)
    return '<h2>Queue & history</h2><p class="meta">Connect this machine to see its Hub jobs.</p>';
  if (!payload)
    return `<h2>Queue & history</h2><p role="status">${error ? "Could not read activity." : "Loading this machine’s jobs…"}</p><button type="button" data-activity-retry ${error ? "" : "hidden"}>Retry</button>`;
  const groups = activityGroups(payload);
  return `<h2>Queue & history</h2>${error ? '<p role="status">Activity may be out of date.</p><button type="button" data-activity-retry>Retry</button>' : ""}${
    Object.entries(groups)
      .filter(([, runs]) => runs.length)
      .map(
        ([group, runs]) =>
          `<section><h3>${{ active: "Now", queued: "Up next", attention: "Needs attention", finished: "Finished" }[group]}</h3>${runs.map((run) => `<article class="desktop-history-row" data-activity-run-id="${e(run.run_id)}"><div class="activity-line"><strong>${e(run.model || run.run_id)}</strong><span class="pill ${run.status === "failed" ? "red" : "grey"}">${e(activityLabels[run.status])}</span></div><p class="meta">${e({ general_assistant: "Chat & reasoning", agentic_coding: "Coding", reasoning: "Reasoning" }[run.use_case] || run.use_case || "Use case unavailable")} · ${run.updated_at || run.created_at ? e(new Date(run.updated_at || run.created_at).toLocaleString()) : "Time unavailable"}</p><div class="actions"><button type="button" data-activity-action="job">View in Hub</button>${run.status === "completed" ? `<button type="button" data-activity-action="results">${errors[run.run_id] ? "Retry results" : "View results"}</button>` : ""}</div>${(results[run.run_id]?.results || []).map((result) => `<div class="activity-result" data-result-id="${e(result.result_id)}"><strong>${e(result.title)} · ${e(result.deployment_profile)}</strong><p class="meta">${result.kind === "report" ? "Compare qualification unavailable." : `${(result.score * 100).toFixed(1)} / 100 · ${result.seconds_per_task.toFixed(2)} s/task`}${result.kind === "compare_context" ? ` · Context only: ${e(result.qualified_count)}/${e(result.attempted_count)} naturally completed tasks; score keeps the full denominator.` : ""}</p><button type="button" data-activity-action="result" data-activity-result-id="${e(result.result_id)}">${result.kind === "report" ? "Open report" : "View in Hub"}</button></div>`).join("")}<details><summary>Run details & logs</summary><p class="meta">${e(run.current_stage || activityLabels[run.status])}${run.error_code ? " · " + e(run.error_code) : ""}</p><button type="button" data-activity-action="job">Open job logs in Hub</button></details></article>`).join("")}</section>`,
      )
      .join("") || '<p class="meta">Nothing queued and no recent jobs.</p>'
  }`;
}
