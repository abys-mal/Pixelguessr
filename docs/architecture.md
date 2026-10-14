# Architecture

Native moderation uses the existing `moderation` app with a dedicated React
layout at `/moderation`. Application permission `moderation.access_workspace`
grants moderator access without Django Admin; only active superusers enter Admin.
Sanction/appeal/report/access commands use per-player first-write locking and
append audit activity. Sanction replacements reverse and link rather than edit
history. `/account-notices` supports the normal account session and a separate
15-minute password-bound notices-only proof for suspended accounts. That proof
is accepted only by notices/appeals endpoints, never by game authentication.
See [current moderation workflows](native-moderation.md).

One Django application and one React application. Local Phase 3 uses SQLite, in-memory cache/channel services, and private local storage. PostgreSQL/Redis remain configured for future use. A lightweight `party_clock` management process advances unattended parties; no external task queue is needed.

```text
Browser → Vite development proxy / production edge → Django ASGI
                                                    ├─ HTTP /api + /admin
                                                    ├─ Channels party sockets + ranked participant sockets
                                                    ├─ SQLite / PostgreSQL: durable domain data
                                                    ├─ In-memory / Redis: cache/throttles + channel layer
                                                    └─ Private filesystem / S3: normalized uploads
```

## Responsibility boundaries

| Backend app | Responsibility                                                                                                                     |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| accounts    | Custom users, public/private serializers, sessions, account permissions, verified titles                                           |
| library     | Category and submission persistence, validated upload pipeline, private references, staff review                                   |
| moderation  | Reports, audited sanctions, active restriction policy, warning acknowledgment                                                      |
| games       | Authoritative singleplayer services, normalized guesses, private reveal compositor, mode availability, durable real-time party services |
| core        | Minimal liveness and database/cache readiness                                                                                      |
| config      | Settings, environment, URL/ASGI wiring                                                                                             |

React uses route-level pages, reusable panels/badges/status messages, one session context, and one CSRF-aware API helper. CSS variables, shared layout classes, and breakpoints support desktop/mobile. Forms call actual APIs; other pages explicitly describe future functionality. The decorative reveal illustration is static and labeled as a visual concept.

## Data and trust

User UUIDs are established in the first migration. Username/email uniqueness is case-insensitive at both validation and database levels. Public profiles omit email and provisional ratings. Clients cannot edit staff status, tiers, titles, or ratings.

Submissions require exactly one image reference. Uploaded filenames are opaque, files are normalized, and external URLs are stored without fetching. The public catalog is an explicit minimal allowlist of ID, category, and creation time. A submitted image is private until reviewed; even approved raw storage references remain private in Phase 2. Review requires staff identity and a timestamp. Staff previews have no-store caching and authorization on every request.

GuestIdentity is bound to the Django server session, with a seven-day identity/session lifetime. Every round read, image request, and guess checks session ownership; UUID knowledge alone grants no access. Accounts own their participant directly, and can also finish a guest round started in the same session. Clearing or losing cookies loses guest access. Never accept client-provided user/guest IDs as authentication.

Participant enforces exactly one account or guest and uniqueness within a match. RoundPlayerState holds signed round scores, solve time (spectator state), and cooldown. Participant holds a nonnegative cumulative score. Guess sequence is unique per round/player. Ranked services enforce registered membership and the one-guess limit under the durable writer gate; foundation model `clean()` also describes identity constraints. Django does not call `clean()` on arbitrary `save()`/`objects.create()`. Singleplayer services validate state in atomic transactions. A first-write match UPDATE locks concurrent guesses before reads, including on SQLite where select_for_update alone has no effect. Unique request IDs make retries idempotent. Party services validate membership and cooldowns under the same first-write locking pattern; ranked services acquire a durable singleton writer gate before mutable reads, making queue pairing, winner selection and Elo application atomic across workers.

Moderation checks start times, expiry, and audited revocation. Warnings remain active after acknowledgment until their 90-day expiry or revocation, but acknowledgment lifts the warning gate. Probation disables submissions and disables ranked. Suspension/closure deny authentication and retrieval of existing session users via the custom auth backend. Admin prevents deletion or editing of issued sanctions and requires superuser status to reverse closure.

## Shared multiplayer implementation contract

- The server creates a private reveal order and authoritative start/deadline. It controls randomness, reveal progress, correctness, cooldowns, scores, spectators, wins, and final Elo.
- Publish only opaque image-delivery tokens, revealed tile coordinates, public participant summaries, authoritative deadlines, and game state. Do not send canonical answers, synonyms, private storage references, or revealing attribution/provenance until an intentional post-round disclosure.
- Prevent downloading the full image at the start of a competitive round. Implement authorized tile delivery or rendered progressive images; a client-side cover over a full image is insufficient.
- Validate account restrictions, match membership, round state, and guess limits inside atomic services. Use row locks/idempotency to decide concurrent guesses and apply Elo once after match completion. Redis is transient transport; PostgreSQL is the durable source of truth.
- Singleplayer: five rounds, 45-second reveal, up to 1,000 points per round, no incorrect penalty/cooldown, forfeit only after full reveal.
- Parties: unlimited guesses, incorrect penalty 50 and cooldown 2 seconds, up to 1,000 points based on reveal progress. Signed round score, cumulative floor zero, solved players spectate, everyone solved ends early.
- Ranked: accounts only, matchmaking only, one guess each, wrong guess consumes the guess without an automatic loss, first correct wins, both wrong or deadline Wash, first four decisive wins ends the match. See ranked.md for Elo, tiers and disconnect policy.
- Party sockets validate origins, reload cookie-session identity, enforce membership on every action, and reconstruct state from the database. Ranked sockets reload authentication and membership on every action and persist connection leases, allowing atomic reconnect/forfeit/No Contest decisions.

## Verification scope

Local regression tests use SQLite/in-memory services; CI is configured for PostgreSQL/Redis. Compose configuration validation runs in CI. Private S3 connectivity and deployment-specific proxy/TLS/storage policy require integration verification in the deployment environment. Singleplayer and party tests verify gameplay, decoded masked-frame pixels, real Channels transport, identity moderation and concurrent departures. Local browser checks cover independent guest sessions. Production integration remains unverified.

## Singleplayer boundaries

`games/services.py` owns session identity, approved hosted-image selection, private answer/synonym and configuration snapshots, randomized reveal order, expiry, idempotent starts, and serialized guess decisions. Reveal count is a pure function of stored start time and server clock. No timers/background jobs are required; state survives cache loss and server restart. Re-review is checked inside the start transaction.

`games/reveal.py` prepares originals only on the server and paints every unrevealed tile opaque before lossless WebP encoding. Its private cache stores normalized source pixels, never a public URL. The endpoint authorizes every request, ignores client reveal-version/timing claims, returns no-store images, and refuses expired/abandoned rounds. Only the revealed prefix of the random order is public. Guess count and canonical completion disclosure are explicit allowlists; synonyms, storage names, image IDs, and source URLs are omitted.

React `useSingleplayer` reconciles server snapshots, handles retry request IDs, polls and reconnects on focus/online, and rejects delayed polls that would undo success/new starts. Its countdown uses a server-clock anchor plus a monotonic cosmetic clock. `Reveal` fetches only masked frames, decodes them before swapping, then fades a decorative grid. Removing the CSS overlay cannot expose hidden pixels. Slow/offline delivery preserves the last confirmed frame until reconnection.

The five-round Match expires after 24 hours by default; this is separate from each 45-second reveal. Full reveal never automatically ends a round. Solved/forfeited rounds retain outcomes, canonical answer and points. Pending rounds stay private. Legacy one-round matches remain read-only history; migrations retain original scores/times/images and only backfill outcomes. Accounts, moderation and future multiplayer models remain intact.

## Five-round persistence and transitions

`Match.singleplayer_round_limit`, `singleplayer_expires_at`, and `singleplayer_revision` distinguish new five-round sessions from legacy one-round data. All five Round records exist at creation. Only round 1 has a start timestamp; Next Round activates one pending successor after the previous outcome is solved/forfeited. Approval is rechecked at activation. Distinct images are preferred; a smaller pool reuses least-used images while avoiding adjacent repetitions.

Scores use existing `RoundPlayerState.score` and `Participant.total_score`. A correct guess freezes the score from actual server reveal count, and the total is recomputed as the sum. Exact integer half-up arithmetic gives 563 at 25% and 63 at 75%; no floating-point rounding discrepancy. Forfeit requires 100% server progress and records a distinct zero-point outcome. Only the fifth completion completes the Match.

Ownership reads occur before opening mutation transactions. The first operation inside a guess/forfeit/advance transaction is a Match UPDATE that acquires the writer lock; then mutable state is re-read. New starts lock the owner before checking for an unfinished game. Request UUIDs and completed outcomes make retries harmless. Persistent revisions let React reject older state, including responses generated at the same timestamp. Expiry and later starts never recalculate prior earned scores.

Current reads restore the latest started round rather than trusting an old browser pointer. Account-owned active sessions can recover on another authenticated browser; guest recovery requires session cookies. React provides explicit round results and Next Round, followed by a dedicated final table and Play Again. Timer values are cosmetic; neither score nor forfeit eligibility is determined by the browser clock.

Tests use in-memory SQLite by default, plus an optional isolated file database for actual simultaneous-request tests. Historical migration compatibility is tested by applying the old schema and upgrading again inside a disposable database. No production/development data is used in automated tests.

## Multiplayer parties

`games/parties.py` owns party membership, host-authorized removal/party bans, presence expiry/terminal transitions, synchronized round transitions, scoring, and safe personalized snapshots. `party_views.py` provides CSRF-protected HTTP actions and secure images; `party_consumer.py` delivers authenticated WebSocket snapshots and guess acknowledgments. Channels only carries invalidations, never shared private answers or essential state. `party_clock` reconciles unattended deadlines.

Party, PartyMember, and PartyCommand persist invites, membership, configuration, presence leases, and idempotent match/lobby commands. Existing Match/Participant/Round/RoundPlayerState/Guess models hold gameplay. Additive games migrations 0005 and 0006 retain historical singleplayer data. PartyMember stores departure reasons and identity bans; PartyCommand records the kick target and ban choice for exact retries. Match and Party store aborted status/reasons. No automatic host succession exists. Round scoring reuses the integer reveal formula and private compositor; a server-only compositor count permits full images after early completion.

React `useParty` reconciles revisions and authoritative timestamps, reconnects WebSockets, and falls back to HTTP using the same guess request UUID after a lost acknowledgment. Guess inputs mount with focus on each new active round; programmatic result-heading focus uses the existing scoped focus style. Genuine keyboard focus remains visible. Native modal confirmation traps focus, starts with Cancel focused, and restores to the trigger or connected lobby/terminal heading. Removed/banned clients stop reconnecting; terminal states stop polling and ignore stale snapshots. Guest names are automatic presentation labels on existing session identities. Active play shows a compact solved count; full tables remain on intermission/final results.

See [party operations, timing, tie-breaking, security, and manual verification](parties.md).

Party presence is a durable 15-second lease from the last confirmed heartbeat; reads and clock ticks reconcile it before renewal. Explicit host leave aborts immediately; an expired host closes/aborts without succession. Expired/removed opponents are marked left, and fewer than two remaining participants aborts even during intermission. Solved spectators count. Abort transitions commit before rejected deadline/expired-member guesses return; they never finalize an unfinished round or advance a successor. Previously accepted scores stay frozen. The existing party first-write lock serializes terminal decisions with guesses, kicks and reconnects on SQLite and PostgreSQL.
