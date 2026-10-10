import {
  pageState,
  setPageState,
  subscribePages,
  patchView,
} from "./desktopState.js";
import {
  renderHome,
  renderModels,
  renderActivity,
  renderSettings,
  homePresentation,
} from "./desktopViews.js";
const navIcons = {
  home: '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
  models:
    '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  activity: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  settings:
    '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="9" cy="18" r="2"/>',
};
const navIcon = (id) =>
  `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${navIcons[id]}</svg>`;
let pages = new Map();
const renderedComponents = new Map();
let renderedLibrary = null;
export function showDesktopPage(id, { focus = true } = {}) {
  if (!pages.has(id)) return;
  for (const [name, page] of pages) page.hidden = name !== id;
  for (const button of document.querySelectorAll("[data-desktop-page]")) {
    if (button.dataset.desktopPage === id)
      button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (focus) pages.get(id).querySelector("h1")?.focus({ preventScroll: true });
  document.querySelector("[data-desktop-content]")?.scrollTo(0, 0);
}
export function openModelCheck() {
  showDesktopPage("models");
  const panel = document.querySelector("[data-check-panel]");
  panel.open = true;
  panel.querySelector("summary").focus();
  panel.scrollIntoView({ block: "nearest" });
}
export function updateHome(state) {
  setPageState("home", state);
}

export function initDesktopNavigation() {
  const frame = document.querySelector("[data-desktop-root]");
  if (!frame) return;
  frame.innerHTML = `<aside class="desktop-side"><a class="desktop-brand" href="#home"><span>IG</span>InferGrade Runner</a><nav aria-label="Runner">${[
    ["home", "Home", "⌂"],
    ["models", "Models", "▤"],
    ["activity", "Activity", "◷"],
    ["settings", "Settings", "⚙"],
  ]
    .map(
      ([id, label, icon]) =>
        `<button type="button" data-desktop-page="${id}">${navIcon(id)}${label}</button>`,
    )
    .join(
      "",
    )}</nav><div class="desktop-machine"><strong>This machine</strong><div class="machine-state"><span data-status-dot class="status-dot"></span><span data-runner-status>Checking…</span></div><div data-slot="admission"></div></div></aside><main data-desktop-content>${[
    ["home", renderHome],
    ["models", renderModels],
    ["activity", renderActivity],
    ["settings", renderSettings],
  ]
    .map(
      ([id, render]) =>
        `<section data-desktop-view="${id}" class="desktop-page" ${id === "home" ? "" : "hidden"}>${render({})}</section>`,
    )
    .join("")}</main>`;
  pages = new Map(
    [...frame.querySelectorAll("[data-desktop-view]")].map((page) => [
      page.dataset.desktopView,
      page,
    ]),
  );
  for (const button of frame.querySelectorAll("[data-desktop-page]"))
    button.onclick = () => showDesktopPage(button.dataset.desktopPage);
  frame.querySelector(".desktop-brand").onclick = (e) => {
    e.preventDefault();
    showDesktopPage("home");
  };
  frame.querySelector("[data-open-check]").onclick = openModelCheck;
  frame.querySelector("[data-go-models]").onclick = () =>
    showDesktopPage("models");
  frame.querySelector("[data-settings-endpoint]").onclick = () => {
    openModelCheck();
    const title = document.querySelector("[data-observed-runtime-panel] h2");
    title.tabIndex = -1;
    title.focus();
    title.scrollIntoView({block:"nearest"});
  };
  frame.querySelector("[data-settings-logs]").onclick = () => {
    showDesktopPage("activity");
    document.querySelector(".log-disclosure").open = true;
  };
  frame.querySelector("[data-copy-logs]").onclick = () =>
    navigator.clipboard
      .writeText(document.querySelector("[data-log-output]").textContent)
      .catch(() => {
        document.querySelector("[data-log-output]").textContent +=
          "\nCould not copy logs; select the text to copy it.";
      });
  for (const button of frame.querySelectorAll("[data-check-use-case]"))
    button.onclick = () => {
      for (const choice of frame.querySelectorAll("[data-check-use-case]"))
        choice.setAttribute("aria-pressed", String(choice === button));
      const select = frame.querySelector("[data-private-use-case]");
      if (select) {
        select.value = button.dataset.checkUseCase;
        select.dispatchEvent(new Event("change"));
      }
    };
  subscribePages((id, state) => {
    const render = {
      home: renderHome,
      models: renderModels,
      activity: renderActivity,
      settings: renderSettings,
    }[id];
    const template = document.createElement("template");
    template.innerHTML = render(state);
    if (id === "home") {
      patchView(
        pages.get(id).querySelector(".hero"),
        template.content.querySelector(".hero").innerHTML,
      );
      document.querySelector("[data-runner-status]").textContent =
        homePresentation(state).title;
      document.querySelector("[data-status-dot]").dataset.state =
        homePresentation(state).title;
      if (Object.hasOwn(state, "assignment")) {
        const current = pages.get(id).querySelector("[data-assignment-panel]"),
          next = template.content.querySelector("[data-assignment-panel]");
        current.hidden = next.hidden;
        current.dataset.state = next.dataset.state;
        // Assignment controls retain their event bindings and recovery visibility.
        for (const selector of [
          "[data-assignment-title]",
          "[data-assignment-description]",
        ])
          current.querySelector(selector).textContent =
            next.querySelector(selector).textContent;
      }
      for (const selector of [
        "[data-machine-hardware]",
        "[data-home-local-models]",
        "[data-home-models]",
      ])
        patchView(
          pages.get(id).querySelector(selector),
          template.content.querySelector(selector).innerHTML,
        );
    }
    if (
      id === "models" &&
      Object.hasOwn(state, "library") &&
      state.library !== renderedLibrary
    ) {
      renderedLibrary = state.library;
      patchView(
        pages.get(id).querySelector("[data-library]"),
        template.content.querySelector("[data-library]").innerHTML,
      );
    }
    for (const [key, component] of Object.entries(state.components || {})) {
      if (renderedComponents.get(id + ":" + key) === component) continue;
      renderedComponents.set(id + ":" + key, component);
      const target = document.querySelector(`[data-slot="${key}"]`);
      if (target) patchView(target, component.render(component.state));
    }
  });
  showDesktopPage("home", { focus: false });
}

export function renderPageComponent(page, key, state, render) {
  const snapshot = pageState(page);
  setPageState(page, {
    components: { ...snapshot.components, [key]: { state, render } },
  });
}
