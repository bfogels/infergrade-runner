# Reported platform hardware names

Real Linux upload acceptance exposed that machine-model detection was macOS-only. Existing chart hardware identity qualification therefore refused Linux/Windows points with an absent machine model. Retain that qualification and record available platform facts for future runs.

Linux reads at most64KiB of `/proc/cpuinfo` for reported CPU model/Hardware and bounded DMI product or device-tree model text. Windows uses fixed read-only CIM queries for Win32_Processor.Name and Win32_ComputerSystem.Model with5s timeout. macOS retains sysctl. No serials, UUIDs or fabricated machine names. Missing/placeholder/invalid model names remain unavailable. Architecture fallback remains a CPU label only; it does not invent a machine model.

Validation: focused17 environment tests and Ruff passed. Five added tests cover Linux reported names/absent DMI/device tree, Windows fixed-query timeout/absence/decoding failure, and placeholders/controls/bounds. Full clean-suite evidence, review and CI are recorded separately. Old uploaded hardware is never rewritten. Emulated Linux on this Mac is not physical second-machine acceptance.
