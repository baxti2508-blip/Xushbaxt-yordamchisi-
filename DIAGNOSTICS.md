# 2026-10-09 investigation and offline repair

## Evidence and access limits

- GitHub `main` was fetched at `f8804da84114d080d04c4428cbf5fcdbec06b27c`.
- The existing 20 offline tests passed before changes.
- GitHub's combined commit status returned no statuses. This cannot establish Render's deployed version.
- Render dashboard presented **Sign In to Render**; no authenticated session was available.
- No local Telegram, OpenAI, or Render API credentials were present. No credentials were created or changed.
- No live Telegram request or OpenAI request was made. Render logs, deployed commit,
  live webhook, active pollers, group membership/privacy/send permissions, `/id`,
  `/holat`, and actual OpenAI billing/model/auth errors remain unverified.
- The root cause of the live incident remains unknown. Code-level blocking is
  established by inspection, but is not proof of the live cause.

## Confirmed code problems and repair

Previously `run()` synchronously invoked `handle()`, media downloads, ffmpeg,
OpenAI calls, dialogue replies, retries, and scheduled speech/reports. All of
these could delay later commands and the next `getUpdates` request.

Polling now dispatches slow messages into a SQLite work queue and processes
non-AI commands directly. A single background thread owns a separate SQLite
connection and serializes all AI/media/timer work. Queue insert and Telegram
offset advancement share a transaction. Pending work survives restarts.
One job is followed by timer/retry work so sustained arrivals cannot starve
reports. `/status`, `/bugun`, and `/tahlil` are queued; `/id` and `/holat` are direct.

`/holat` and startup logs include the bot.py SHA256 prefix. `/holat` additionally
shows job count, worker activity, polling timestamps/errors, and whether AI
settings exist. Existence of settings is explicitly not a live API verification.
Missing AI settings no longer prevent Telegram-only diagnostics from starting.

An active webhook still stops polling by default, with a safe, explicit message.
For an intentional switch from webhook to polling, set
`DELETE_WEBHOOK_ON_START=true`; deletion preserves pending updates and its result
is checked. No webhook was deleted during this investigation. Telegram requires
webhook and getUpdates delivery modes to be used separately:
https://core.telegram.org/bots/api#getupdates
https://core.telegram.org/bots/api#deletewebhook

Regular Telegram requests have a 10-second transport timeout; long polling has
50 seconds for a 40-second server wait. HTTP 409 identifies a possible competing
poller/webhook; 401 identifies a rejected Telegram token. Exception URLs/bodies
are never logged by the runtime error handlers. Existing OpenAI error mapping
is tested for 401, 403, 404, quota/rate-limit 429, and 500.

## Verification

Run from this repository:

```sh
python -m unittest -q
python -m py_compile bot.py test_runtime.py
git diff --check
```

28 tests passed: the original 20 plus 8 runtime regressions. The added tests
prohibit unmocked network access. They exercise the actual polling loop and
background thread with video analysis deliberately blocked, and verify that
`/id` and `/holat` are answered before that analysis is released and that polling
offset continues advancing. They also cover durable queue/restart/dedup,
webhook opt-in preserving backlog, missing AI settings, failed analysis plus
failed warning delivery, redacted API errors, transport timeouts, and isolation.
This verifies local behavior only; it is not a successful live Telegram/video test.

## Remaining live verification (no secrets in output)

1. In Render, identify this repository's service. Compare the active deploy's
   full commit against the selected repair commit, not only `main`. Verify it
   is a running background worker with a persistent `DATA_DIR`, one replica,
   and no other service polling with the same token.
2. Compare startup `code_sha256` and `/holat` SHA256 with the deployed bot.py.
   Expected value can be computed locally with
   `python -c "import hashlib; print(hashlib.sha256(open('bot.py','rb').read()).hexdigest()[:10])"`.
3. Read Render logs for startup, polling HTTP 401/409, receipt metadata,
   worker failure, and permission checks. Never copy token-bearing URLs,
   environment values, headers, raw API responses, or media contents.
4. Server-side `getWebhookInfo`: inspect only whether URL is present and
   pending count. Deliberately choose delivery mode before removing a webhook.
5. Server-side `getMe`/`getChatMember`: check privacy, membership, and send
   permissions. In the intended group run `/id` and compare group/user IDs
   with configured IDs, then `/holat`. These commands do not call OpenAI.
6. A successful real media test requires separately authorized paid API use.
   Send one small media sample and verify a new `last_visual_success`, an
   actual AI result, and `/id`/`/holat` responsiveness while it is processing.
   An acknowledgement alone does not establish analysis success.

## Limitations

- This repair is not deployed or merged by this investigation.
- Existing PR #1 handles dialogue reply double-batching; this change does not
  duplicate that work: https://github.com/baxti2508-blip/Xushbaxt-yordamchisi-/pull/1
- SQLite durability requires persistent storage. Work is at-least-once across
  abrupt shutdowns: a crash after a remote API call but before local completion
  may repeat a call or reply. Queue durability does not promise exactly-once AI.
- A single slow worker can still delay later media/report jobs, but it no longer
  blocks polling or direct commands. Telegram network/send delays can still
  delay direct commands within their configured transport timeouts.
- Missing AI configuration is diagnostic-only operation; it cannot analyze media.
- Manual failed `/tahlil` jobs can be requested again. Automatic media failures
  retain the existing bounded media retry mechanism.
