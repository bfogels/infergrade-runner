import { setPageState } from "./desktopState.js";
import { renderPageComponent } from "./desktopNavigation.js";
import { escapeHtml } from "./desktopViews.js";
export function hfCredentialSummary(state) {
  if (state?.environment_override)
    return "Using a token from this app’s environment; removing a saved token does not unset it.";
  return state?.saved
    ? "A Hugging Face token is saved in this machine’s OS credential store."
    : "No token saved by Runner.";
}
export function renderHf({ state, pending, error } = {}) {
  return `<h2 tabindex="-1" class="sr-only">Hugging Face</h2><p data-hf-status role="status">${escapeHtml(error || hfCredentialSummary(state))}</p><button type="button" data-hf-retry ${error ? "" : "hidden"} ${pending ? "disabled" : ""}>Retry</button><details><summary>Add a token</summary><form data-hf-form><label>Read access token<input type="password" name="token" autocomplete="off" spellcheck="false" maxlength="256" placeholder="hf_…" required></label><div class="actions"><button type="submit" ${pending ? "disabled" : ""}>Verify and save</button><button type="button" data-hf-tokens>Create token</button></div></form></details><button type="button" data-hf-remove ${pending || !state?.saved ? "disabled" : ""}>Remove token</button>`;
}
export function initHfCredentials({ invoke, openExternal }) {
  const panel = document.querySelector('[data-slot="hf"]');
  if (!panel) return;
  panel.className = "setting-row desktop-hf";
  let generation = 0,
    state = null,
    pending = false,
    error = "";
  const emit = () =>
    renderPageComponent("settings", "hf", { state, pending, error }, renderHf);
  const request = async (command, args) => {
    const own = ++generation;
    pending = true;
    error = "";
    emit();
    try {
      const call = await invoke();
      if (!call) throw Error("Open the desktop app to manage tokens.");
      const payload = await call(command, args);
      if (own !== generation) return;
      state = payload;
      if (command === "save_desktop_hf_credential")
        setPageState("home", { needsHf: false });
    } catch (problem) {
      if (own === generation)
        error =
          typeof problem === "string"
            ? problem
            : problem?.message || "Could not change the token; try again.";
    } finally {
      if (own === generation) {
        pending = false;
        emit();
      }
    }
  };
  panel.onsubmit = (event) => {
    event.preventDefault();
    const input = panel.querySelector("input"),
      token = input.value;
    input.value = "";
    request("save_desktop_hf_credential", { token });
  };
  panel.onclick = (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (button.matches("[data-hf-remove]"))
      request("clear_desktop_hf_credential");
    if (button.matches("[data-hf-retry]"))
      request("desktop_hf_credential_status");
    if (button.matches("[data-hf-tokens]"))
      openExternal("https://huggingface.co/settings/tokens").catch(() => {
        error =
          "Could not open Hugging Face; visit huggingface.co/settings/tokens.";
        emit();
      });
  };
  window.addEventListener("focus", () =>
    request("desktop_hf_credential_status"),
  );
  request("desktop_hf_credential_status");
}
