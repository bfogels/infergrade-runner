const HOSTED_API_URL = "https://api.infergrade.com";

function isLocalHost(hostname) {
  const host = String(hostname || "").toLowerCase();
  const ipv4Octet = "(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)";
  return host === "localhost" || host === "::1" || host === "[::1]" || new RegExp(`^127(?:\\.${ipv4Octet}){3}$`).test(host);
}

function hasScheme(value) {
  return String(value || "").includes("://") && /^[a-z][a-z0-9+.-]*:/i.test(value);
}

export function normalizeDesktopApiUrl(value = "") {
  const raw = String(value || "").trim();
  const candidate = raw || HOSTED_API_URL;
  if (/\s/.test(candidate)) {
    throw new Error("Enter a valid Hub API URL, such as https://api.infergrade.com.");
  }

  let urlText = candidate;
  if (!hasScheme(urlText)) {
    const hostGuess = urlText.split(/[/:]/, 1)[0];
    urlText = isLocalHost(hostGuess) ? `http://${urlText}` : `https://${urlText}`;
  }

  let parsed;
  try {
    parsed = new URL(urlText);
  } catch (_error) {
    throw new Error("Enter a valid Hub API URL, such as https://api.infergrade.com.");
  }

  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && isLocalHost(parsed.hostname))) {
    throw new Error("Hosted Hub URLs must use HTTPS. Localhost and 127.0.0.1 can use HTTP for development.");
  }
  if (!parsed.hostname) {
    throw new Error("Enter a valid Hub API URL, such as https://api.infergrade.com.");
  }
  return parsed.href;
}

export function userSafeUpdateFailure(_message = "") {
  return "Update status is unavailable. You can still pair and start the Runner.";
}

export function isCredentialCanceled(message = "") {
  return /cancelled|canceled|user interaction|user.*cancel/i.test(String(message || ""));
}

export function userSafeTokenFailure(message = "") {
  if (isCredentialCanceled(message)) {
    return "Credential storage was canceled. You can retry, reset pairing, or paste a fresh code.";
  }
  if (/already exists|duplicate|ambiguous/i.test(String(message || ""))) {
    return "Credential storage needs to replace the saved token. Try Reset Pairing, then pair again.";
  }
  return "Credential storage is unavailable. You can retry, reset pairing, or paste a fresh code.";
}
