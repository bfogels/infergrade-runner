# Security Policy

InferGrade Runner executes benchmark workloads on user machines and emits result bundles that may be shared with InferGrade Hub. Please treat security issues, credential handling, sandboxing boundaries, and misleading provenance as sensitive.

## Reporting A Vulnerability

Do not open a public issue for suspected vulnerabilities or leaked secrets.

Email Brian Fogelson at <brianf888@gmail.com> with:

- a short description of the issue
- affected component or path, if known
- reproduction steps or a proof of concept, when safe to share
- whether any token, certificate, private key, signing material, or private run artifact may have been exposed

You should receive an acknowledgment within 3 business days. If the issue is accepted, maintainers will coordinate a fix, validation, and disclosure timing based on severity.

## Secrets And Sensitive Artifacts

Never commit or attach:

- `.env` files
- Hub API tokens, runner tokens, or pairing responses
- private model registry credentials
- Apple certificates, App Store Connect API keys, Tauri updater signing keys, passwords, or notarization material
- private keys, SSH keys, TLS certificates, provisioning profiles, or keychain exports
- private benchmark inputs or proprietary run artifacts

Support exports are designed to omit bearer tokens, but review any artifact before sharing it publicly.

## Release-Signing Boundary

Public macOS desktop releases must be built through the protected GitHub `release` environment. Release signing and notarization secrets belong in that environment only, with access restricted to release jobs from `main` and maintainer review when GitHub plan support is available.

Fork pull requests must not receive signing, notarization, package-publishing, Hub, or model-registry secrets. Do not use `pull_request_target` for untrusted code paths.

## Supported Versions

Until the first public stable release, only the current `main` branch and the latest preview release artifacts receive security fixes.
