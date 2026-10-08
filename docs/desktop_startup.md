# Open at login

The installed release app exposes an opt-in Settings control. Reading the OS entry never creates it; a fresh installation starts off. Opening at login opens the application; it does not bypass pairing, sleep, or benchmark admission.

macOS uses a user LaunchAgent with an XML-serialized ProgramArguments array. Linux uses a user freedesktop autostart entry, with the installed AppImage path when applicable and two-stage Exec quoting. Windows uses a quoted HKCU Run entry, bounded to the documented 260-character command limit. The app never overrides Windows Startup approval. Unreadable, malformed or unknown approval states remain unconfirmed.

Changes are serialized and keep the desktop lifecycle guard until OS IO completes. The UI displays only confirmed readback, preserves actionable errors, and allows refresh after failure. A differently configured entry is never overwritten or deleted. Moving an installation requires removing its old login entry in OS settings first. Development, temporary, translocated, and read-only macOS installer-volume execution cannot register startup. Linux paths containing unsupported field-expansion characters fail before mutation.

Native tests use temporary files and an isolated Windows registry key. Linux package CI additionally launches an isolated desktop entry through gio to verify spaces and reserved-character quoting. macOS plist parsing, real filesystem inspection, controller confirmation/failure behavior and light/dark responsive keyboard checks are distinct from actual OS login acceptance. No user login settings are changed by QA.
