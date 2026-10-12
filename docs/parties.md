# Multiplayer parties — Phase 3

## Run locally

Use the existing `.env`, SQLite database, `.venv`, and frontend dependencies. Do not reset the database or seed images again. From `C:/Users/actian/python code/Pixelguessr`, use three PowerShell terminals:

```powershell
# Terminal 1
cd backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

```powershell
# Terminal 2
cd frontend
npm run dev
```

```powershell
# Terminal 3
cd backend
..\.venv\Scripts\python.exe manage.py party_clock
```

Open `http://localhost:5173/party/new`. On Linux/macOS substitute `../.venv/bin/python` in backend commands. The clock accepts `--once` for operational checks. It advances unattended rounds and closes expired parties; reads/WebSocket snapshots also reconcile deadlines after restart. No Docker, Redis, or external task queue is required locally.

For two independent sessions use normal/private browser windows or different browsers. For local automated/manual verification, localhost and 127.0.0.1 also have separate cookies. Guests must retain their session cookies to resume. Sharing the same cookie identity across tabs intentionally resumes one player rather than creating duplicates.

For two devices on a trusted LAN, use the computer's LAN address with Vite port 5173, and explicitly add that frontend origin to `CSRF_TRUSTED_ORIGINS` and the relevant allowed host to `ALLOWED_HOSTS` in your environment. Vite already binds to 0.0.0.0 and proxies API/WebSockets to the local backend. Do not weaken origin checks or expose private-media. LAN testing is optional; no environment changes are needed for same-computer testing.

## Rules and timeline

- Six-character cryptographically random uppercase alphanumeric invite, accepted case-insensitively; shareable `/party/CODE` URL.
- Maximum 12 members; minimum two to start. Account display names come from the account; duplicate account names receive deterministic suffixes. Guest names are validated and duplicate names rejected clearly.
- Host can change only reveal duration (15/30/45/60 seconds, default 30) and round count (5/10/15/20, default 10) in the lobby. All eligible approved hosted images/categories are used.
- Every round has the same server-generated 20×20 order, image, three-second start countdown, and reveal deadline for all players. Reveal size remains configured by the existing grid setting.
- Incorrect guesses cost 50 points and impose a durable two-second cooldown. Correct guesses freeze exact half-up `1000 × (1 − revealed_count/total_tiles)^2`, less 50 per wrong guess. Unsolved round scores are negative penalties only. Total is `max(0, previous_total + round_score)`.
- Solved players spectate the same masked reveal and standings. Answers remain hidden from every client until deadline or all remaining non-left participants solve. Offline participants remain scored; their absence cannot extend the deadline.
- Full image, answer, curated credits, round ranking, and total leaderboard appear for five seconds after every round, including the last. Next rounds start automatically with a new three-second countdown. Final standings identify all players tied at the highest total as winners.
- Any member can return the completed party to its lobby; membership remains and a new match starts with fresh scores. Mid-match joins are rejected; existing members reconnect to the same state.

Overall display order: total descending, solved-round count descending, sum of solve elapsed times ascending, membership join time ascending, then UUID. Secondary keys do not remove tied winners. Round ranking: round score descending, solve timestamp ascending (unsolved uses deadline), participant join time, then UUID.

Presence uses five-second browser heartbeats and a 15-second connected lease. Explicit host departure transfers to the longest-standing remaining member immediately. A temporary disconnect preserves the host for 45 seconds before succession to the longest-standing recently present member. If nobody is present, a returning member can become host. Parties expire 24 hours after creation; records remain for audit rather than being destructively purged.

## Persistence and security

The additive games migration `0005_match_party_round_limit_and_more` adds Party/PartyMember/PartyCommand and extends existing gameplay records. It neither recreates the database nor modifies image approval/storage. Existing singleplayer scoring and progression remain unchanged.

The party database row's first-write UPDATE serializes mutations on SQLite and PostgreSQL. Durable request UUIDs protect create/start/lobby/guess retries; persisted cooldowns prevent refresh/API bypass. A lost WebSocket acknowledgment falls back to HTTP with the same UUID. Scores and completion finalize once. No essential game state depends on channel/cache memory.

Every HTTP action validates membership, session identity, and account restrictions; guest mutations require CSRF too. WebSockets validate origins and reload the current cookie-session identity, including logout/revocation, before reads/actions. Invalidations carry no private answer; each connection receives its own safe snapshot. Guess payloads cannot select another participant or override points.

The existing private compositor renders only the server-authorized revealed prefix. The browser never receives an unobscured original at round start. Query parameters cannot request a future frame; pending image IDs and future reveal order stay private. Full reveal after early completion is a server-only compositor option. Canonical completion disclosure never includes synonyms, storage paths, identifying filenames, or raw guesses.

## Two-session manual test plan

1. Create as guest Avery in window A with 15 seconds and five rounds. Verify Start Game is disabled with one player. Copy the link. Join in independent window B as Robin, using the lowercase code once. Check both member lists update; only A has editable settings/Start Game. Try a duplicate guest name and an invalid code separately.
2. Save 60 seconds/five rounds in A; verify B's summary updates. Start. Check both three-second countdowns, same tile pattern/deadline, and disabled join/settings while playing.
3. Submit a deliberately wrong answer with Enter in A. Check −50 and two-second disabled submission. Refresh immediately: cooldown, round, time, score, and membership should remain. Type during cooldown and submit again when it expires.
4. Identify the image and submit its canonical answer or curated synonym in A. Check spectator state and focused result heading, continued reveal, and no answer disclosure in B. Have B solve: both see full image/answer/credits/ranks and advance after five seconds. Next active inputs should focus automatically; held Enter should not activate new controls.
5. Leave one round unsolved to its deadline. Check negative wrong-guess score, total floor zero, full image, and automatic next round. Disconnect B temporarily or refresh during this flow; reconnect must restore the active round/solved status, never restart it.
6. Verify final-round results remain visible for five seconds before final standings. Verify a tied zero-score match shows both winners. Return to Lobby from B; check both retain membership and host settings unlock. Start a new match and check totals reset.
7. In a lobby, explicitly leave as host and verify B receives host controls. Separately close/reopen the host session inside 45 seconds (host retained), then leave it closed beyond 45 seconds while B stays connected (B becomes host). An unattended active match still completes with the clock running.
8. Repeat representative create/join/guess/result flows at a 390px mobile width and with keyboard Tab/Enter. Visible rings must remain on keyboard controls, while programmatically focused headings have no dotted outline.
9. Optional isolated test database: mark every image pending and confirm Start shows a clear empty-library error; restore approval through moderation. Do not change your real curated library to exercise this case; automated tests already cover it.

## Verification and limits

Automated suites cover real Channels socket authentication/guess delivery, image pixels and premature-answer protection, cooldown/replay/floor scoring, host succession, capacity/start/guess races, deadline catch-up, recovery, and frontend transports/focus. File-backed isolated SQLite enables concurrent-request cases; in-memory SQLite deliberately skips those cases. Linux path conventions are supported, but local execution was on Windows; existing CI retains PostgreSQL/Redis coverage.

The local in-memory layer supports one ASGI server process. A separate clock process writes durable state, observed by one-second WebSocket reconciliation; its in-memory invalidations are not shared across processes. Production must use existing PostgreSQL/Redis settings (`USE_SQLITE=False`, `LOCAL_SERVICES=False`), an ASGI server, and a supervised clock process. Redis and PostgreSQL deployments, physical-device networks, and 12-player load/performance were not exercised locally.

Snapshot delivery is roughly once per second and network latency may make decorative fades differ slightly; scoring/reveal access always uses the actual server clock. Production frame caching, transport/edge abuse controls, load testing, observability, and cleanup retention policies are recommended next. Guest access requires retained cookies. A small approved library can reuse images, avoiding adjacent repeats where possible. Ranked, category selection, chat, and fuzzy guesses remain deferred.
