# Desktop browser connection — 2026-10-07

Home Connect and Settings Connect in browser use the shipped Hub device-code
protocol. The device secret remains native-memory only; the renderer receives a
short code, HTTPS approval URL and expiry. Existing pasted-code and Hub-opening
paths remain available. Successful approval uses the existing OS credential
store/profile completion and normal listener startup/readiness handling.

Native cancellation, replacement pairing, token reset and legacy-code redemption
use generation fences under the pairing mutation lock. Late responses cannot
replace a newer pairing. Approval becomes terminal before asynchronous startup;
Stop waiting disappears and disconnect/repair are disabled until startup returns.
Network retries expire, denial is terminal, and polling respects slowdown.
Device requests have bounded timeouts, do not follow redirects and expire idle
connections before the Hub five-second keepalive boundary.

Actual isolated localhost Hub HTTP protocol validation passed: native Rust issue,
pending response, signed fresh development-account approval, redemption, safe
UI projection and second-redemption rejection. In-memory credential stores were
used for this protocol check; the native OS keyring was not exercised. No model
or benchmark was run. The Mac remains locked for native UI acceptance.

Five renderer tests cover success, late issue/approval cancellation, expiry,
denial and terminal approval before delayed startup. Desktop check59/build,
Rust43 tests plus one opt-in protocol test and clippy validation passed.
`./scripts/test_all.sh` passed1174 Python tests plus tier/product audits.
Home Connect Enter opens Settings and the honest development-view message.
Eight Home/Settings1060px/375px light/dark captures report no overflow; four
Settings captures were visually inspected. Native OS-keyring/app acceptance
remains pending. This remains one slice of the desktop redesign.
