// Local UI snapshots contain no credentials or command authority.
const snapshots = { home: {}, models: {}, activity: {}, settings: {} };
const subscribers = new Set();
export function pageState(page) {
  return snapshots[page];
}
export function setPageState(page, patch) {
  snapshots[page] = { ...snapshots[page], ...patch };
  for (const listener of subscribers) listener(page, snapshots[page]);
}
export function subscribePages(listener) {
  subscribers.add(listener);
  return () => subscribers.delete(listener);
}
const keyAttributes = [
  "data-activity-run-id",
  "data-result-id",
  "data-model-id",
  "data-home-result-action",
  "data-gpu-uuid",
  "data-private-report-id",
];
function nodeKey(node) {
  if (node.nodeType !== 1) return null;
  for (const key of keyAttributes)
    if (node.hasAttribute(key)) return key + ":" + node.getAttribute(key);
  return null;
}
// Reconcile by semantic identity so polling cannot transfer a focused action to
// another run. Stable controls retain handlers, drafts and open disclosures.
export function patchView(target, markup) {
  const focused = target.contains(document.activeElement)
    ? document.activeElement
    : null;
  const template = document.createElement("template");
  template.innerHTML = markup;
  function patch(parent, children) {
    const existing = [...parent.childNodes],
      used = new Set();
    children.forEach((next, index) => {
      const key = nodeKey(next);
      let current = key
        ? existing.find((node) => !used.has(node) && nodeKey(node) === key)
        : existing[index];
      if (current && (used.has(current) || nodeKey(current) !== key))
        current = null;
      if (
        !current ||
        current.nodeType !== next.nodeType ||
        current.nodeName !== next.nodeName
      ) {
        current = next.cloneNode(true);
        parent.insertBefore(current, parent.childNodes[index] || null);
        used.add(current);
        return;
      }
      used.add(current);
      if (parent.childNodes[index] !== current)
        parent.insertBefore(current, parent.childNodes[index] || null);
      if (next.nodeType === 3) {
        if (current.nodeValue !== next.nodeValue)
          current.nodeValue = next.nodeValue;
        return;
      }
      if (next.nodeType !== 1) return;
      for (const attr of [...current.attributes])
        if (!next.hasAttribute(attr.name) && attr.name !== "open")
          current.removeAttribute(attr.name);
      for (const attr of [...next.attributes])
        if (current.getAttribute(attr.name) !== attr.value)
          current.setAttribute(attr.name, attr.value);
      if (current instanceof HTMLInputElement && next.type === "checkbox")
        current.checked = next.hasAttribute("checked");
      patch(current, [...next.childNodes]);
    });
    for (const stale of existing) if (!used.has(stale)) stale.remove();
  }
  patch(target, [...template.content.childNodes]);
  if (
    focused &&
    focused.isConnected &&
    !focused.disabled &&
    document.activeElement !== focused
  )
    focused.focus({ preventScroll: true });
}
