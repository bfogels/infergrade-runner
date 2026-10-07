# Runner device authorization v1

Bare `infergrade pair` defaults to https://api.infergrade.com. It sends detected
hostname, execution mode, and environment to `POST /api/runner/device-codes`.
The response follows `runner_device_authorization.schema.json` (issueResponse).
Runner displays only user_code and verification_uri, then polls
`POST /api/runner/device-codes/token` (pollRequest). Successful polling returns
tokenResponse: the same durable runner_profile as legacy pairing.

Hub returns pollError with HTTP 400 for authorization_pending, slow_down,
access_denied, expired_token, or invalid_grant. HTTP 429 also slows polling.
Runner waits the supplied interval before polling, increases it by five seconds
on slow_down, and stops at expires_in. Device secrets never appear in output.

Authenticated Hub users inspect reported hardware/hostname using
`POST /api/runner/device-codes/inspect` with a user_code, then approve or deny
via `POST /api/runner/device-codes/approve` (approvalRequest). Inspection cannot
return the device secret. Approval binds the request to the approving account;
issuance is anonymous, bounded, rate limited, and expires after ten minutes.
Codes are single use; denied, expired, and consumed requests cannot mint tokens.
Use a uniform wrong-code response, account/IP limits and an account lockout for
repeated wrong entries. Record approval/denial in the account security history.
Durable state transitions and token minting must be atomic across API processes.

Existing INFERGRADE_PAIR_CODE, --pair-code-stdin and --pair-code retain their
precedence. `--prompt-pair-code` accepts a Hub-issued legacy code with hidden
input on a TTY. A missing device endpoint (404/501) also offers this fallback;
network errors, denial, or expiry never switch flows silently. Noninteractive
clients can use device authorization or one of the existing scripted paths.

Environment is Runner-reported discovery, not hardware attestation. Timing
measurements and job authorization remain separate contracts.
