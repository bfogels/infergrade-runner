import { escapeHtml as e } from "./desktopViews.js";
const toggle = (label, checked, disabled) =>
  `<label class="switch"><input type="checkbox" aria-label="${label}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}></label>`;
const retry = (error, pending) =>
  `<button type="button" data-retry ${error ? "" : "hidden"} ${pending ? "disabled" : ""}>Retry</button>`;
const errorText = (error) =>
  `<p role="status" ${error ? "" : "hidden"}>${e(error)}</p>`;
export function renderStartup({ state, pending, error } = {}) {
  return `<h2>Open at login</h2>${toggle("Open Runner at login", state?.enabled, pending || !!error || !state?.available)}${errorText(error || state?.warning)}${retry(error, pending)}`;
}
export function renderNotifications({
  state,
  pending,
  error,
  noticeError,
} = {}) {
  return `<h2>Finish notifications</h2>${toggle("Notify when a benchmark finishes", state?.enabled, pending || !!error || !state?.available)}${errorText(error || noticeError || state?.warning)}${retry(error, pending)}<button type="button" data-off ${error ? "" : "hidden"} ${pending ? "disabled" : ""}>Turn off</button>`;
}
export function renderMachine({ key, name, busy, error } = {}) {
  return `<h2>This machine</h2><form><input type="text" aria-label="Machine name" maxlength="120" autocomplete="off" value="${e(name)}" ${!key || busy || !name ? "disabled" : ""}><button type="submit" hidden>Save name</button>${retry(error, busy)}${errorText(error)}</form>`;
}
export function renderGpu({ saved, pending, error } = {}) {
  const disabled = pending || !saved?.available || !!error,
    selected =
      saved?.devices.filter((d) => d.selected).map((d) => d.uuid) || [];
  return `<h2>GPUs</h2><div class="seg" role="group" aria-label="GPUs"><button type="button" data-gpu-default aria-pressed="${!selected.length}" ${pending ? "disabled" : ""}>Default</button>${(saved?.devices || []).map((d) => `<button type="button" data-gpu-uuid="${e(d.uuid)}" title="${e(d.model)} · ${e(d.vram_gb)} GB" aria-pressed="${selected.length === 1 && selected[0] === d.uuid}" ${disabled ? "disabled" : ""}>GPU ${e(d.index)}</button>`).join("")}${saved?.devices.length === 2 ? `<button type="button" data-gpu-both aria-pressed="${selected.length === 2}" ${disabled ? "disabled" : ""}>Both</button>` : ""}</div>${(saved?.devices.length || 0) > 2 ? `<form>${saved.devices.map((d) => `<label><input type="checkbox" name="gpu" value="${e(d.uuid)}" ${d.selected ? "checked" : ""} ${disabled ? "disabled" : ""}>GPU ${e(d.index)} · ${e(d.model)}</label>`).join("")}<button type="submit" ${disabled ? "disabled" : ""}>Save selected GPUs</button></form>` : ""}<p class="meta" ${error ? "hidden" : ""}>${saved?.available ? "Applies to your next benchmark; both splits a model across the two GPUs." : "GPU choice is available on machines with NVIDIA GPUs."}</p>${errorText(error)}${retry(error, pending)}`;
}
export function renderAdmission({ paused, pending, error } = {}) {
  return `<label class="pause-label">Pause new jobs <span class="switch">${toggle(
    "Pause new benchmarks",
    paused === true,
    pending || paused === null || !!error,
  )
    .replace('<label class="switch">', "")
    .replace(
      "</label>",
      "",
    )}</span></label>${errorText(error)}${retry(error, pending)}`;
}
export function renderBackground({ state, pending, error } = {}) {
  return `<h2 tabindex="-1">Keep running in background</h2>${toggle("Keep running in background", state?.keep_running, pending || !state?.tray_available)}${errorText(error || state?.warning || (!pending && state?.tray_available === false ? "The system tray is unavailable; keep this window open." : ""))}${retry(error, pending)}`;
}
export function renderStorage({ saved, pending, error } = {}) {
  const format = (bytes) =>
    `${((bytes || 0) / 1024 ** 3).toLocaleString(undefined, { maximumFractionDigits: 1 })} GiB`;
  return `<h2>Storage</h2><div class="storage-summary"><strong>${saved ? format(saved.managed_bytes) + " in InferGrade downloads" : "Checking downloads…"}</strong><span>${saved ? format(saved.disk_free_bytes) + " free on disk" : ""}</span></div><meter min="0" max="1" value="${saved?.limit_bytes ? Math.min(1, saved.managed_bytes / saved.limit_bytes) : 0}" aria-label="Downloads as a proportion of the saved limit" ${saved && saved.limit_bytes ? "" : "hidden"}></meter><div class="actions"><label>Download cap <select aria-label="Download size limit" ${pending || !saved || error ? "disabled" : ""}><option value="unknown" ${saved ? "hidden" : ""}>Unavailable</option>${[25, 50, 100, 200].map((limit) => `<option value="${limit}" ${saved?.limit_gb === limit ? "selected" : ""}>${limit} GiB</option>`).join("")}<option value="none" ${saved?.limit_gb === null ? "selected" : ""}>No limit</option></select></label>${retry(error, pending)}</div><p class="meta" title="Lowering the cap asks before removing the oldest unkept InferGrade downloads; external files are preserved.">${saved ? format(saved.kept_bytes) + " kept · " + format(saved.reserved_bytes) + " reserved" : "Checking saved storage…"}</p>${errorText(error)}`;
}
