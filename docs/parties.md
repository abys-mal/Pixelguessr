# Multiplayer parties — Phase 3.1

## Run locally

Use the existing `.env`, SQLite database, `.venv`, and frontend dependencies. Do not reset the database or seed images again. From `C:/Users/actian/source/Pixelguessr`, use three PowerShell terminals:

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

Open `http://localhost:5173/party/new`. On Linux/macOS substitute `../.venv/bin/python` in backend commands. The clock accepts `--once` for operational checks. It completes unattended rounds and closes expired parties; reads/WebSocket snapshots also reconcile deadlines after restart. Intermissions wait for the host and never advance automatically. No Docker, Redis, or external task queue is required locally.

For two independent sessions use normal/private browser windows or different browsers. For local automated/manual verification, localhost and 127.0.0.1 also have separate cookies. Guests must retain their session cookies to resume. Sharing the same cookie identity across tabs intentionally resumes one player rather than creating duplicates.

For two devices on a trusted LAN, use the computer's LAN address with Vite port 5173, and explicitly add that frontend origin to `CSRF_TRUSTED_ORIGINS` and the relevant allowed host to `ALLOWED_HOSTS` in your environment. Vite already binds to 0.0.0.0 and proxies API/WebSockets to the local backend. Do not weaken origin checks or expose private-media. LAN testing is optional; no environment changes are needed for same-computer testing.

## Rules and timeline

- Six-character cryptographically random uppercase alphanumeric invite, accepted case-insensitively; shareable `/party/CODE` URL.
- Maximum 12 members; minimum two to start. Account display names come from the account; duplicate account names receive deterministic suffixes. Guests receive server-generated names such as Guest 4821, unique within the party. Creation/joining has no name field. The same cookie identity resumes the same membership/name across refreshes and reconnects; names never authenticate or authorize.
- Host can change only reveal duration (15/30/45/60 seconds, default 30) and round count (5/10/15/20, default 10) in the lobby. All eligible approved hosted images/categories are used.
- Every round has the same server-generated 20×20 order, image, three-second start countdown, and reveal deadline for all players. Reveal size remains configured by the existing grid setting.
- Incorrect guesses cost 50 points and impose a durable two-second cooldown. Correct guesses freeze exact half-up `1000 × (1 − revealed_count/total_tiles)^2`, less 50 per wrong guess. Unsolved round scores are negative penalties only. Total is `max(0, previous_total + round_score)`.
- Solved players spectate the same masked reveal. Active/countdown/spectator screens show only a compact solved-player count; full leaderboard tables appear during intermission and final results. Answers remain hidden from every client until deadline or all remaining non-left participants solve. Offline participants remain scored; their absence cannot extend the deadline.
- Full image, answer, curated credits, round ranking, and total leaderboard remain visible after each non-final round until the host clicks **Next Round**. Other players see **Waiting for host…**. This begins the existing synchronized three-second countdown. The final round completes directly into final standings, identifying all players tied at the highest total as winners; there is no Next Round control there. Return to Lobby is unchanged.
- Any member can return the completed party to its lobby; membership remains and a new match starts with fresh scores. Mid-match joins are rejected; existing members reconnect to the same state.

Overall display order: total descending, solved-round count descending, sum of solve elapsed times ascending, membership join time ascending, then UUID. Secondary keys do not remove tied winners. Round ranking: round score descending, solve timestamp ascending (unsolved uses deadline), participant join time, then UUID.

Presence uses five-second browser heartbeats and a 15-second lease from the last confirmed presence. WebSocket loss alone does not remove anyone: a refresh or another tab can renew the same membership. HTTP fallback reads renew presence too. An arrival after lease expiry cannot resurrect an ended match or re-enter an active match. On initial entry to the existing party URL, an inactivity-expired member attempts one join through the normal endpoint; it succeeds only in an open lobby with space. Failure shows the server explanation and navigation without a retry loop. Intentional Leave Party never triggers automatic rejoining. The clock and server reads reconcile expiry before accepting a new heartbeat. This means detection is approximately 10–15 seconds after an actual disconnect with normal five-second heartbeats. Initial connection setup uses loading/joining feedback; the reconnecting banner appears only after an established WebSocket is lost.

Unbanned host removal offers **Rejoin Party** on the existing URL. Refreshing alone does not undo a kick. Banned identities receive no rejoin control and remain denied server-side. All successful rejoins reuse the existing member identity and guest cookie security. Closed, expired, full and already-started parties remain subject to the existing server checks.

The manual transition is `POST /api/parties/CODE/next/` with `round_id` and a UUID `request_id`, under the existing party writer lock and command replay protection. Only the current host can use it. It targets the completed round, preventing delayed commands from skipping later rounds. Duplicate UUIDs are safe replays; competing fresh requests cannot activate multiple rounds. WebSockets deliver state updates; they do not accept advancement commands. Round `ended_at` is the durable intermission state, so no new migration or ephemeral timer is required. `next_starts_at` and `rules.results_seconds` are now null. Storage/eligibility errors leave the intermission intact for an explicit host retry. Presence, host-departure, minimum-player and expiration rules continue during intermission.

The lobby shows the complete invitation URL with an accessible **Copy invite link** icon and brief checkmark feedback. Clipboard failure leaves the URL selectable with an explanation. Desktop intermissions put the image/answer/credits beside host controls and a bounded, keyboard-scrollable standings panel; mobile stacks the panels. Both existing round and overall rankings retain their original ordering and scores.

Removed/unavailable and other party exit actions use a local wrapping flex group
with a 12px gap; global button styling is unchanged. On authoritative round completion,
guessing closes immediately. The party presentation retains the image layout until
the decoded, server-authorized full frame has painted, then shows intermission or
final standings. Completed party frames skip the decorative tile fade. This is only
a presentation handoff: deadlines, scoring, server transitions and peer synchronization
are unchanged. Reload picture remains available on image failure; View results lets
the player proceed if the image is unavailable or slow. Another host's advancement
or a terminal access/departure event still supersedes the local presentation.

Parties has no per-round forfeit endpoint. Leave Party removes membership and may
abort the match; it does not disclose the remaining image. Singleplayer forfeit is
a separate action permitted only after its full authorized reveal. Its presentation
and the ranked renderer are outside this party-specific correction.

There is **no automatic host succession**. Explicit host Leave Party closes a lobby immediately or aborts an active match with “The host left the party.” Expired host presence closes/aborts with “The host disconnected.” Opponents retain membership during the same grace period. An explicit leave, kick, or expired opponent lease that leaves fewer than two participants aborts an active match with “Not enough players remain.” Solved spectators count as participants. The rule applies during countdowns and intermissions too. An aborted match freezes already accepted scores, awards no additional points, exposes no new answer/image, and never advances or restarts. Remaining clients receive a focused Match ended screen and Return Home. Lobby closures have a Party closed screen. Parties expire 24 hours after creation; records remain for audit.

Only the host sees the subtle X beside other lobby members. It becomes red on hover/keyboard focus and opens **Remove player?** rather than immediately removing anyone. Cancel/Escape dismiss and restore focus. **Prevent this player from re-joining** starts unchecked. Confirmation without it permits a later explicit lobby rejoin; checked confirmation stores a party-specific identity ban. Removed connections receive a notice, stop reconnecting, and cannot guess/read images/perform actions. Ban enforcement uses account IDs or the existing guest session identity, never names. A new browser guest identity can bypass a guest ban; this is best-effort party moderation, not device enforcement.

## Persistence and security

The additive games migration `0005_match_party_round_limit_and_more` adds Party/PartyMember/PartyCommand and extends existing gameplay records. It neither recreates the database nor modifies image approval/storage. Additive migration `0006_party_management_and_departures` adds departure/ban reasons, aborted states, and kick command identity/target fields without rewriting historical records. Existing singleplayer scoring and progression remain unchanged.

The party database row's first-write UPDATE serializes mutations on SQLite and PostgreSQL. Durable request UUIDs protect create/start/lobby/kick/guess retries; a kick retry cannot remove a player again after an explicit rejoin. Terminal transitions are idempotent and serialized with guesses/reconnects; persisted cooldowns prevent refresh/API bypass. A lost WebSocket acknowledgment falls back to HTTP with the same UUID. Scores and completion finalize once. No essential game state depends on channel/cache memory.

Every HTTP action validates membership, session identity, and account restrictions; guest mutations require CSRF too. WebSockets validate origins and reload the current cookie-session identity, including logout/revocation, before reads/actions. Invalidations carry no private answer; each connection receives its own safe snapshot. Guess payloads cannot select another participant or override points.

The existing private compositor renders only the server-authorized revealed prefix. The browser never receives an unobscured original at round start. Query parameters cannot request a future frame; pending image IDs and future reveal order stay private. Full reveal after early completion is a server-only compositor option. Canonical completion disclosure never includes synonyms, storage paths, identifying filenames, or raw guesses.

## Two-session manual test plan

1. Open independent normal/private browser sessions A and B (or localhost and 127.0.0.1). In A open `/party/new`, choose 60 seconds/five rounds and create. Verify no guest-name field, an automatic Guest name, and disabled Start Game with one member. Join in B using the lowercase invite code. Verify unique names and only A has host controls; neither account profile is changed.
2. In A click B’s X. Check its neutral/red hover and keyboard focus, confirmation wording, unchecked checkbox, initial Cancel focus and Tab containment. Escape/Cancel must restore focus to the X without removing B. Confirm unchecked: B sees Removed from party and never automatically rejoins, including after refresh. Explicitly join again in B: same guest name/membership returns.
3. Remove B with the checkbox checked. Refresh B and explicitly try the code: rejoin must be denied. Create a different party in A and join B there to verify the ban is party-specific. Accounts are tested using the same account in another authenticated session; guest protection depends on retained session cookies.
4. Start a two-player match. Check synchronized countdown/reveal, focused guess input, compact `0 of 2 players solved`, and no full leaderboard. Submit a wrong guess with Enter: −50 and two-second cooldown remain unchanged. Refresh during play/cooldown and verify round/name/score recover rather than duplicate membership.
5. Solve in A with a canonical answer or curated synonym. A spectates; B must still have no canonical answer/credits. Solve in B: both receive the full answer/image, round scores, solved/unsolved status and cumulative standings. Wait longer than five seconds and refresh: the intermission must remain. Only A sees Next Round; B sees Waiting for host…. Click Next Round in A and verify both see the three-second countdown and focused new-round inputs. Leave another round unsolved through its deadline. Verify final standings/winners with no Next Round and unchanged Return to Lobby.
6. In a fresh active match have B explicitly Leave Party; A immediately sees Match ended / Not enough players remain. Repeat with host A explicitly leaving: B sees The host left the party. During another active match navigate A away without Leave Party, then return quickly: match/name must recover. Repeat beyond 15 seconds while B stays connected: B sees The host disconnected; a late A return must not restart anything.
7. Repeat host explicit departure and expired presence in the lobby: B sees Party closed and never receives host controls. With three sessions, remove/disconnect one opponent: the match continues with two. Solved spectators continue counting. Removing the last opponent during intermission must abort without advancing.
8. Repeat representative lobby/dialog/guess/result flows at narrow and mobile widths with Tab/Enter. Focus indicators remain visible on keyboard controls; disappearing targets return focus to a connected heading. Tables scroll horizontally if required. No local database/image changes are necessary to exercise empty-library behavior; automated tests use isolated image libraries.

## Verification and limits

Automated suites cover real Channels socket authentication/guess delivery, image pixels and premature-answer protection, cooldown/replay/floor scoring, host-only kick/ban enforcement, grace/abort transitions, automatic guest identities, capacity/start/guess/leave/kick/reconnect races, deadline catch-up, recovery, and frontend transports/focus. File-backed isolated SQLite enables concurrent-request cases; in-memory SQLite deliberately skips those cases. Linux path conventions are supported, but local execution was on Windows; existing CI retains PostgreSQL/Redis coverage.

The local in-memory layer supports one ASGI server process. A separate clock process writes durable state, observed by one-second WebSocket reconciliation; its in-memory invalidations are not shared across processes. Production must use existing PostgreSQL/Redis settings (`USE_SQLITE=False`, `LOCAL_SERVICES=False`), an ASGI server, and a supervised clock process. Redis and PostgreSQL deployments, physical-device networks, and 12-player load/performance were not exercised locally.

Snapshot delivery is roughly once per second and network latency may make decorative fades differ slightly; scoring/reveal access always uses the actual server clock. Production frame caching, transport/edge abuse controls, load testing, observability, and cleanup retention policies are recommended next. Guest access requires retained cookies; creating a fresh identity bypasses a guest-specific ban. A small approved library can reuse images, avoiding adjacent repeats where possible. Ranked, category selection, chat, and fuzzy guesses remain deferred.

Suspension/closure immediately ends a hosted party and removes everyone, or removes only a restricted non-host. Warning/probation leave parties unaffected. See [moderation enforcement](moderation-enforcement.md) for current policy and recovery behavior.
