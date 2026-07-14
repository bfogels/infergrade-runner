# InferGrade Runner 0.3.20

Runner 0.3.20 adds a proof-gated llama.cpp candidate intake lane and the native
structured-chat protocol required to benchmark Gemma 4 without weakening the
stable runtime path.

## Included

- discover new upstream llama.cpp releases daily and report pin age without
  silently promoting them;
- keep b9050 and the canonical llama.cpp container on the stable path while
  exposing b9994 only through the explicit `reviewed_candidate` channel;
- pin candidate release assets and the candidate container source to immutable
  digests;
- support Gemma 4 direct-answer tasks through llama-server's structured chat
  protocol with thinking disabled;
- fail Qwen3.6 direct-answer tasks closed until a compatible native runtime and
  hardware canary exist;
- keep Runner contract 0.3.14 because this release does not change the result
  or Hub request schemas.

## Evidence boundary

A full local Gemma 4 E4B canary completed on Apple M4 Pro with the pinned b9994
macOS candidate: deployment inference completed, all five capability cases
produced scorable answers, and all eight constraint checks passed. This proves
that exact artifact/runtime/machine path. It does not promote b9994 to the
stable channel, prove Gemma 4 12B fit, validate Qwen3.6, or establish
cross-hardware performance or capability claims.
