# Ranked Duel — Phase 4

Ranked is registered-only matchmaking; it is separate from private parties. Guests can still play singleplayer and parties. Probation, suspension and closure prevent ranked entry; warnings do not. Active restrictions forfeit an ongoing duel with the existing Elo rules applied exactly once. See [moderation enforcement](moderation-enforcement.md). No placement phase, account-age gate, chat, spectators, invites or direct rematches.

## Rules and privacy

Pairing starts one shared 3-second versus countdown. Both players receive the same 45-second reveal with one guess each. Canonical answers and curated synonyms use the existing case/whitespace/punctuation normalization. A wrong guess uses that player's guess without awarding a win. The first accepted correct guess ends the round immediately. Both wrong or the 45-second deadline without a correct guess ends in Wash. Washes never add decisive wins; there is no total-image or wash limit. First to four decisive wins ends the match (at most seven decisive rounds).

Intermediate results reveal the full image, canonical answer, attribution, round winner or Wash, and score for five seconds. A new image starts automatically only when both participants are connected. The fourth win opens persistent final results. Play Again enters ordinary matchmaking, with no special opponent preference.

Only approved hosted images use the existing private storage pipeline. Images are distinct within a match until the pool is exhausted, then least-used choices avoid adjacent repeats when possible. No lifetime exposure ledger is created. An empty library returns a clear error; withdrawal between rounds pauses on the completed result and retries when images return. Existing original CC0 development images retain their documented attribution and explicit review requirement.

Before completion, participants receive only server-confirmed revealed tile indices, masked WebP frames, timers and whether each player used their guess. Full reveal order, answers, synonyms, source filenames and private storage paths remain private. Frame query parameters cannot increase reveal progress. Ranked does not store submitted guess text. Match state and images require an authenticated participant on every request; there is no live public match view. Public history contains only completed outcomes, score and rating snapshots.

## Matchmaking

The lobby keeps the existing Elo emblem, concise reveal/guess/win rules and separate
standings/menu navigation. Competitive SVG icons appear only beside profile Elo and
with tier names in standings/the ranked journey. Unknown tiers have no invented icon;
Pro, Master and Legend remain honorary titles rather than competitive tiers.

Participant snapshots add `round.incorrect_guess_ids`, derived from recorded guess
timestamps without a solved timestamp. This contains participant IDs only and never
guess text. During an active round, the client derives a muted inline opponent
incorrect-guess status directly from this field beneath the guess controls. It stays
visible until the round ends and reconstructs on refresh or reconnection from the
current snapshot, without timers or notification history. A missing field on an
older server produces no inferred status.
Correct guesses retain normal results. This addition changes no guessing or scoring
rules and requires no migration.

The dedicated queue is entered only through Find opponent. Each account has one queue entry and cannot enter another active ranked match. Cancel applies to the current UUID ticket; a cancellation that loses the atomic pairing race returns the already-created match. Leaving the queue page closes its socket and cancels its ticket. Disconnected/stale searches expire rather than remain in background matchmaking.

Actual wait seconds / maximum Elo gap: **0 / 100, 15 / 150, 30 / 250, 60 / 400, 90 / 600, 120 / 800**. Both players' current windows must allow the gap. Search never exceeds 800. Fairness policy: process oldest queued player first, choose their closest eligible opponent, then break equal gaps by oldest queue time and UUID. This deterministic policy avoids bypassing older eligible players to optimize later pairs. No player is paired with themselves.

## Elo and public standings

New accounts start at **1000 Elo**. Existing stored ratings are preserved by migration. Expected score is `E = 1 / (1 + 10 ** ((opponent_before - player_before) / 400))`. Final rating is `max(100, round_half_up(player_before + K * (S - E)))`, where `S` is 1 for a win or 0 for a loss. Decimal arithmetic and whole-rating half-up rounding make decisions deterministic. Independent K: **40 for the first 20 rated matches** (previous count 0–19), **24 thereafter**. There is no maximum or decay. Independent K, rounding and the floor mean rating changes need not be zero-sum.

Victory and forfeits increment both rated counts and the appropriate win/loss counters. Rating application, match completion and participant before/after/delta snapshots occur in the same atomic transaction and cannot repeat. No Contest changes neither rating nor counters and does not grant leaderboard eligibility. History displays it clearly with zero delta.

Derived tiers: below 1200 no tier badge; Bronze 1200, Silver 1400, Gold 1600, Diamond 1800. The existing legacy tier database field remains for compatibility but public values are derived, never rewritten as a second source of truth. Existing staff-verified titles are preserved; this phase adds no title logic. Tier definitions and starting Elo displayed in standings come from server configuration.

Public `/players/<username>` shows exact Elo, tier when applicable, wins, losses, rated matches, member date and paginated history without email. `/leaderboards` sorts active rated players by descending Elo, then case-insensitive username and UUID, with global positions and profile links. My position is a database count query, not an in-memory scan. Both APIs use the existing page size (24).

## Disconnects and recovery

Each socket has a durable connection row; closing one tab does not disconnect another tab for that account. Heartbeats run every five seconds. A missing heartbeat expires a 12-second durable lease, covering half-open connections or server-process failure. Explicit socket closes record server time immediately. A **30-second grace** starts at observed disconnect (or inferred lease expiry). Reconnect before the deadline restores the same round, score, used guess and original reveal deadline. The active reveal continues, and the opponent may still win it. New rounds wait while either player is disconnected.

Explicit Leave match forfeits immediately with normal Elo. A single expired grace forfeits. If both disconnect timestamps differ by **at most two seconds**, neither has reconnected in time, and **both own 30-second deadlines** expire, the result is No Contest. The first deadline alone does not forfeit this case. One timely reconnect cancels the double-disconnect condition and the remaining absent player forfeits at their deadline. Outside the two-second window, the earliest expired disconnect loses. An expired player cannot clear their timestamp or guess during the other player's remaining No Contest deadline. All decisions use the same durable database writer gate.

## Local startup and migrations (no Docker)

The existing lightweight `.env`, virtual environment and frontend install remain sufficient; no Redis/PostgreSQL runtime is required. From the existing project:

```powershell
cd "C:/Users/actian/python code/Pixelguessr/backend"
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

In three additional terminals:

```powershell
cd "C:/Users/actian/python code/Pixelguessr/frontend"
npm run dev
```

```powershell
cd "C:/Users/actian/python code/Pixelguessr/backend"
..\.venv\Scripts\python.exe manage.py party_clock
```

```powershell
cd "C:/Users/actian/python code/Pixelguessr/backend"
..\.venv\Scripts\python.exe manage.py ranked_clock
```

Open http://localhost:5173/ranked. The ranked clock drives matchmaking and disconnect/round deadlines even with no clients; sockets and HTTP reads also reconcile overdue state. `ranked_clock --once` performs one recovery pass. ASGI/Channels support is provided by the existing Daphne app. Keep both clocks running to support both multiplayer modes.

Additive migrations: accounts `0002_user_ranked_losses_user_ranked_matches_and_more`, games `0007_rankedgate_match_ranked_message_match_ranked_outcome_and_more`. Existing users, approved images, parties and singleplayer records retain their values. No records are reset. `games/ranked_rules.py` centralizes tuning; optional `.env` `RANKED_CONFIG` is a JSON object overriding defaults. Example: `RANKED_CONFIG={"early_k":40,"established_k":24}`. Keep valid positive timing, sorted zero-based search windows and ascending tiers. Grid size uses existing `SINGLEPLAYER_GRID_SIZE`.

## Verification

Run the README local checks. Default backend tests use disposable in-memory SQLite. Real writer-race tests require file-backed SQLite (or the existing PostgreSQL CI settings). PowerShell example, from backend:

```powershell
$rankedTemp = Join-Path $env:TEMP ('pixelguessr-tests-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $rankedTemp | Out-Null
$env:TEMP = $rankedTemp
$env:TMP = $rankedTemp
$env:TEST_SQLITE_FILE = Join-Path $rankedTemp 'test.sqlite3'
..\.venv\Scripts\python.exe -m pytest -q
```

Linux equivalent: `ranked_tmp=$(mktemp -d); TEST_SQLITE_FILE="$ranked_tmp/test.sqlite3" ../.venv/bin/python -m pytest -q`. Neither command targets `backend/db.sqlite3`. There is no pytest base-temp configuration; a fresh OS temporary directory also avoids stale Windows temp permissions.

Two registered accounts checklist (separate browser profiles, or localhost and 127.0.0.1):

1. Guest sees sign-in. Registered account opens ranked; it does not queue until Find opponent. Verify elapsed seconds, expanding search and Cancel.
2. Queue both accounts. Verify automatic pair, shared versus countdown, pre-match ratings, private reveal and active score.
3. Enter one wrong guess. Opponent does not receive a win. Both wrong yields Wash; waiting to 45 seconds also yields Wash. After five seconds both inputs are fresh and focused.
4. Correct guess wins immediately. Repeated Enter cannot activate Leave or the next screen. Four decisive wins produces Victory/Defeat with both rating snapshots; refresh preserves results.
5. Refresh one active client within 30 seconds: same reveal deadline, score and used guess. Disconnect during results: no new image until restored. Test explicit Leave and a single expired grace.
6. Disconnect both within two seconds; after both 30-second deadlines verify No Contest and no Elo/counter/leaderboard changes. Reconnect one early to verify the other forfeits instead.
7. Check paginated leaderboard/profile/history, profile links, no badge below 1200, and Play Again through ordinary queue. Check desktop and mobile, mouse and Tab focus.

## Limits and next steps

The database gate deliberately serializes ranked decisions for correctness on SQLite and PostgreSQL. Queue scans and once-per-second personalized state/reveal rendering are suitable for local use; load-test and optimize them before public scale. Redis configuration is preserved, but correctness does not rely on an in-memory Channels group. Production workers share database state; isolated in-memory channels should remain development-only. Clock recovery is durable, while results may arrive one polling tick late and browser countdowns are cosmetic. Server-observed half-open disconnects include the documented presence lease before grace.

Linux/PostgreSQL/Redis infrastructure is not available in this local Windows verification. Existing CI configuration can exercise them when you push. Add production monitoring, supervised clock processes, compositor load testing and edge rate controls next. Account email verification/recovery and production deployment remain separate future work. Normal-session appeals are available on Account Notices (`/account-notices`).

## Ranked synchronization (Phase 4.1)

The browser maintains a persistent monotonic presentation clock. The initial HTTP state read and authenticated WebSocket clock replies supply round-trip samples; the midpoint estimates server time, low-latency samples are preferred, and corrections are slewed rather than resetting countdowns. Clock messages do not renew presence. The existing heartbeat and 30-second reconnect rules are unchanged. All phase changes and guess acceptance still come from server state.

Ranked sockets reconcile on shared wall-clock quarter seconds. Reveal permissions are quantized to the round's 250ms timeline, so the two players receive matching frame identifiers. The image endpoint honors the snapshot's `v` tile count exactly and rejects invalid, negative, or future counts. Authorization and round reconciliation occur before cache access. Masked WebP bytes are cached for 60 seconds, with bounded process-local locks coalescing concurrent rendering. Redis continues to provide shared caching when configured; locks coalesce only within one process.

`RankedReveal` maintains one in-flight frame, skips superseded pending frames, and does not refetch unchanged frame URLs on heartbeat or clock snapshots. It reveals only the loaded frame's authorized tile prefix and validates the response count. It cannot reveal pixels before a secure frame arrives. Singleplayer and party delivery remain unchanged. Slow networks/devices can lag; normal local conditions should remain within about one frame, without waiting for the other browser.

Ranked socket startup is deferred until after React's immediate StrictMode cleanup. Cleanup cancels retries and heartbeats, ignores old-socket callbacks, and lets an already-started handshake finish before closing it. Vite's proxy configuration and error reporting are unchanged. A development `write ECONNABORTED` means the proxy attempted to write to an aborted socket; the former duplicate/early-close lifecycle could trigger this condition. Local browser verification reproduced both Vite ECONNABORTED log messages by closing a socket 10ms into its opening handshake. The corrected Ranked refresh, navigation, and completion paths did not emit those errors; the historical log alone cannot identify which particular closure triggered it. Genuine failures remain visible as Reconnecting or Disconnected.

For a two-browser check, sign into separate accounts, queue together, compare the three-second countdown and 45-second reveal, refresh one browser midway, then test a correct answer, both incorrect, and a timeout. Results should count down together for five seconds before fresh inputs appear. Check for a single live socket per client in DevTools and clean navigation/Play Again cleanup. On leaderboard and public profiles, check centered pagination at desktop and narrow mobile widths, including disabled buttons and Tab navigation.
