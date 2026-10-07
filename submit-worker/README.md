# pcdj-submit Worker

A Cloudflare Worker that receives Petite Cup du Jour logs from `submit.html` and hands them to the operator's PC. The PC side is `submissions_poll.py` in the repo root, which runs `new_petite.py` on each submission. Publishing stays manual.

```
submit.html  --POST /submit-->  Worker + KV  <--GET /pending, /log/<id>--  submissions_poll.py
             <--GET /status---               <--POST /status/<id>--------  (Task Scheduler, 15 min)
```

It is a copy of the COTD Worker (`zeepkist cotd elo/submit-worker`), deployed as a separate Worker with its own KV so a change here can never break COTD submissions. Free tier only: Workers + Workers KV need no payment card.

## Storage (KV binding `SUBMISSIONS`)

| Key | Value |
|---|---|
| `log:<id>` | Raw log bytes. Metadata holds `community`, `sha256`, `size`. |
| `sub:<id>` | The submission record (JSON). The authoritative copy. |
| `sha:<sha256>` | Id of the submission with that exact file (dedupe). |
| `index` | JSON array of records, newest first, capped at `MAX_INDEX`. |

Record fields: `id, community, map1, mapper1, map2, mapper2, exclude, date, submitter, created, updated, status, size, sha256, n_blocks, preview, summary, note`. No IP address, user agent or Turnstile data is stored.

`community` is the community PCDJ number (the "#52" in the map names). The internal "Petite Cup N" is assigned by `new_petite.py`, never by the submitter: the community numbering skips the Troll and Roulette specials, so the two drift apart.

Ids look like `20261007T2109-12142fb0` (UTC minute plus 8 random hex digits).

## Endpoints

Every response is JSON except `/log/<id>`. Errors are `{"ok": false, "error": "<code>", "message": "...", "details": {...}}`, with CORS headers so the page can show the message.

| Method and path | Who | What |
|---|---|---|
| `GET /` | anyone | Health check. |
| `POST /submit` | the site (Origin allowlist + Turnstile) | Multipart: `file`, `community`, `map1`, `mapper1`, `map2`, `mapper2`, `exclude` (JSON array), `date`, `submitter`, `preview` (JSON), `cf-turnstile-response`. |
| `GET /status` | anyone | Last 50 records. |
| `GET /pending` | poller | Records with status `received` or `processed`. |
| `GET /log/<id>` | poller | Log bytes, `X-Sha256` header. |
| `POST /status/<id>` | poller | `{"status", "note"?, "summary"?}`. |
| `POST /reindex` | poller | Rebuild `index` from the `sub:` records. |

Poller endpoints need `Authorization: Bearer <POLLER_TOKEN>`.

`/submit` rejects:

- files over 5 MB or without COTDTracker elimination rounds;
- PCDJ numbers outside 1 to 999, a missing map name, and dates more than 60 days old;
- any value starting with `--`, or containing a line break;
- excluded names containing a comma (`--exclude` is comma separated);
- more than `DAILY_SUBMIT_CAP` submissions in 24 hours.

Mappers are optional. `new_petite.py` excludes a mapper only if they were in the lobby.

An identical file (same SHA-256) returns the earlier id with status `duplicate` and stores nothing.

### Known limitation: the index

`index` is read, modified and written back, so two writes landing at the same moment can drop one record from it. The `sub:` records are never lost. `POST /status/<id>` puts a missing record back, and the poller calls `/reindex` once a day.

## One-time setup

The Cloudflare account, the wrangler login and the Turnstile widget already exist (set up for COTD on 2026-10-06), so only these steps remain. Run them in this folder.

1. `npm install`.
2. Create the KV namespaces and paste both ids into `wrangler.toml`:
   ```
   npx wrangler kv namespace create PCDJ_SUBMISSIONS
   npx wrangler kv namespace create PCDJ_SUBMISSIONS --preview
   ```
3. Reuse the `cotd-submit` Turnstile widget: it already allows `aizpunr.github.io` and `localhost`, and its site key is in `submit.html`. Copy the widget's **secret key** from the Cloudflare dashboard (Turnstile, `cotd-submit`) and, in PowerShell:
   ```
   Get-Clipboard | npx wrangler secret put TURNSTILE_SECRET
   ```
   Pasting with Ctrl+V into wrangler's prompt cancels it in PowerShell 5.
4. Make a NEW poller token (never reuse the COTD one), store it in the Worker and in `submit_config.json` (repo root, gitignored):
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   npx wrangler secret put POLLER_TOKEN
   ```
   ```json
   {"worker_url": "https://pcdj-submit.cotd-submit.workers.dev", "poller_token": "<token>"}
   ```
5. `npx wrangler deploy`. Check the printed URL matches `PROD_WORKER_URL` in `submit.html`.
6. Smoke test the Turnstile secret with a fake token: the error codes must say `invalid-input-response`. `invalid-input-secret` means a wrong value was stored.
7. Register the poller (runs as you, only while you are logged on, which the toasts need). In PowerShell:
   ```
   $py = "C:\Users\rafa\AppData\Local\Programs\Python\Python310\pythonw.exe"
   $action = New-ScheduledTaskAction -Execute $py -Argument '"C:\Users\rafa\Desktop\Claude\petite cup stats\submissions_poll.py" --once' -WorkingDirectory "C:\Users\rafa\Desktop\Claude\petite cup stats"
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
   $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
   $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
   Register-ScheduledTask -TaskName "PCDJ submissions poll" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
   ```
   Plain `schtasks /TR` quoting breaks in PowerShell on the spaces in the path. The poller uses the `certifi` CA bundle: Python's default store on Windows can fail on workers.dev certificates with "certificate has expired".
   Then run `python submissions_poll.py --once -v` once by hand and check `cup logs/submissions/poll.log`.

## Day to day

| Task | Command |
|---|---|
| Local Worker (uses `.dev.vars`, simulated KV) | `npx wrangler dev --port 8787` |
| Live logs | `npx wrangler tail` |
| Deploy a change | `npx wrangler deploy` |
| Pause the poller | create `cup logs/submissions/PAUSE`; delete it to resume |
| Poller dry run | `python submissions_poll.py --once --dry-run -v` |
| Stop the scheduled task | `schtasks /Change /TN "PCDJ submissions poll" /DISABLE` |

`.dev.vars` (gitignored) holds Cloudflare's always-pass Turnstile test secret and `POLLER_TOKEN=devtoken`. On localhost, `submit.html` talks to `http://127.0.0.1:8787` with the matching test site key. Port 8787 is shared with the COTD Worker's `wrangler dev`, so run only one at a time.

## Rotating the poller token

Generate a new token, run `npx wrangler secret put POLLER_TOKEN`, and update `submit_config.json`. The next poller pass uses it.

## Free tier limits that matter

The limits are per Cloudflare ACCOUNT, so they are shared with the COTD Worker.

- 1,000 KV writes per day. A submission costs 4 writes and a status change costs 2.
- 1,000 KV list operations per day. Only `/reindex` lists, once a day per Worker.
- 25 MB per KV value. Logs are capped at 5 MB and are usually under 0.5 MB.
- 100,000 Worker requests per day.
