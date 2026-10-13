import { pageState, setPageState } from "./desktopState.js";
import { renderPageComponent } from "./desktopNavigation.js";
import { escapeHtml as e } from "./desktopViews.js";
export function selectableLocalModel(path, discoveredPath = null) {
  return (
    typeof path === "string" &&
    path.length > 0 &&
    (path.toLowerCase().endsWith(".gguf") || path === discoveredPath)
  );
}
// Local file discovery is diagnostic until an exact artifact is verified.
export function discoveryRows(payload) {
  return (Array.isArray(payload?.files) ? payload.files : [])
    .filter(
      (file) =>
        typeof file?.path === "string" &&
        typeof file?.name === "string" &&
        Number.isFinite(file?.size_bytes) &&
        file.size_bytes >= 0 &&
        file.read_only === true,
    )
    .slice(0, 500);
}
export function renderDiscovery({ payload, pending, error } = {}) {
  const files = discoveryRows(payload),
    folders = (Array.isArray(payload?.folders) ? payload.folders : [])
      .filter((v) => typeof v === "string")
      .slice(0, 16);
  const summary = pending
    ? "Checking local files…"
    : error ||
      `${files.length ? files.length + " local model" + (files.length === 1 ? "" : "s") + " found" : "No local models found"}${payload?.scan_complete === false ? "; some folders could not be fully scanned" : ""}.`;
  return `<h2 tabindex="-1" class="sr-only">Local model folders</h2><p data-discovery-status role="status">${e(summary)}</p>${folders.map((folder) => `<div class="discovered-folder" data-model-id="folder:${e(folder)}"><span>${e(folder)}</span><button type="button" data-remove-folder="${e(folder)}" aria-label="Stop scanning ${e(folder)}" ${pending ? "disabled" : ""}>Stop scanning</button></div>`).join("")}<div class="actions"><button type="button" data-discovery-refresh ${error ? "" : "hidden"} ${pending ? "disabled" : ""}>Retry files</button><button type="button" data-discovery-add ${pending ? "disabled" : ""}>Add a folder…</button></div>`;
}
export function initModelDiscovery({ invoke, chooseFolder }) {
  const panel = document.querySelector('[data-slot="discovery"]');
  if (!panel) return;
  panel.className = "drawer-panel desktop-discovery";
  let generation = 0,
    payload = null,
    pending = false,
    error = "";
  const emit = () =>
    renderPageComponent(
      "models",
      "discovery",
      { payload, pending, error },
      renderDiscovery,
    );
  const request = async (command, args) => {
    const own = ++generation;
    pending = true;
    error = "";
    emit();
    try {
      const call = await invoke();
      if (!call) throw Error("Open the desktop app to discover local files.");
      const next = await call(command, args);
      if (own !== generation) return;
      payload = next;
      const files = discoveryRows(payload);
      setPageState("models", {
        library: { ...pageState("models").library, found: files },
      });
      setPageState("home", { localModels: files.map((file) => file.name) });
    } catch (problem) {
      if (own === generation)
        error =
          problem?.message ||
          "Could not inspect local files; check folder access and retry.";
    } finally {
      if (own === generation) {
        pending = false;
        emit();
      }
    }
  };
  panel.onclick = async (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (button.dataset.removeFolder)
      request("set_desktop_model_folder", {
        folder: button.dataset.removeFolder,
        remove: true,
      });
    if (button.matches("[data-discovery-refresh]"))
      request("desktop_discovered_models");
    if (button.matches("[data-discovery-add]")) {
      try {
        const folder = await chooseFolder();
        if (typeof folder === "string")
          await request("set_desktop_model_folder", { folder, remove: false });
      } catch {
        error =
          "Could not open the folder picker; try again in the desktop app.";
        emit();
      }
    }
  };
  window.addEventListener("focus", () => request("desktop_discovered_models"));
  request("desktop_discovered_models");
}
