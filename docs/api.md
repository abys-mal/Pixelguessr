# Phase 2.1 API

All paths have trailing slashes. JSON responses unless noted. Session cookies authenticate requests. Before an unsafe request, GET `/api/auth/csrf/` and send the returned `csrfToken` in `X-CSRFToken`; send cookies on the same origin. Registration/login rotate the CSRF secret. The React helper gets a fresh token for each mutation. There are no JWTs or tokens in browser localStorage.

| Method | Path                                            | Access / result                                                                               |
| ------ | ----------------------------------------------- | --------------------------------------------------------------------------------------------- |
| GET    | `/api/health/live/`                             | Public process liveness                                                                       |
| GET    | `/api/health/ready/`                            | Public DB/cache readiness; 503 with no internal errors on failure                             |
| GET    | `/api/auth/csrf/`                               | Public masked CSRF token + cookie                                                             |
| POST   | `/api/auth/register/`                           | CSRF required; username, email, password, optional display_name; creates session; 201         |
| POST   | `/api/auth/login/`                              | CSRF required; username/password; creates session                                             |
| POST   | `/api/auth/logout/`                             | Session + CSRF; 204                                                                           |
| GET    | `/api/auth/me/`                                 | Public; `{user: null, restrictions: null}` for guests, private user/restrictions for accounts |
| PATCH  | `/api/auth/me/`                                 | Account access + CSRF; only display_name editable                                             |
| GET    | `/api/auth/profiles/<username>/`                | Public profile without email or rating                                                        |
| GET    | `/api/library/categories/`                      | Public nonpaginated categories                                                                |
| GET    | `/api/library/catalog/`                         | Public approved metadata, paginated; no answers/URLs                                          |
| GET    | `/api/library/submissions/`                     | Eligible account; own submissions only, paginated                                             |
| POST   | `/api/library/submissions/`                     | Eligible account + CSRF; JSON external reference or multipart private upload; 201 pending     |
| GET    | `/api/library/submissions/<uuid>/preview/`      | Staff with account access; private streamed WebP, no-store; external references return 404    |
| POST   | `/api/moderation/reports/`                      | Account access + CSRF; subject user UUID, category, details; 201                              |
| GET    | `/api/moderation/sanctions/`                    | Session; own active sanctions, paginated                                                      |
| POST   | `/api/moderation/sanctions/<uuid>/acknowledge/` | Session + CSRF; own active warning only; idempotent                                           |
| GET    | `/api/modes/`                                   | Public intended rules; gameplay_available=true; singleplayer and parties available=true              |

Standard paginated result: `{count, next, previous, results}` (24 per page). Validation failures are 400, denied session permissions 403, unknown objects 404, and throttled requests 429. Login failure has a generic error; production should add edge abuse controls. CSRF failure may use Django’s HTML error body; the frontend never displays raw HTML.

Submission fields: `canonical_answer` (120 chars), `accepted_synonyms` (JSON list, max 30 strings of 120 chars), `category` (integer ID), `source` (`commons`, `licensed`, `ai`, `manual`), `source_url` (HTTPS provenance required for commons/licensed), `license` (160 chars), `attribution` (500 chars), and exactly one of `external_image_url` or `image_file`. With multipart, encode accepted_synonyms as a JSON string. Upload limits: 8 MB, still JPEG/PNG/WebP, minimum 64 px per side, maximum 4096 px per side and 12 MP. Client-supplied status, reviewer, owner, and storage keys are never accepted as writable fields. Public catalog output includes only `id`, nested category metadata, and `created_at`.

Throttle scopes: anonymous 120/hour, user 1200/hour, login/register 10/minute, image creation 20/day, reports 10/day. Scoped endpoints use their scope rather than both generic scopes. Configure trusted proxy count according to real infrastructure; the default trusts no forwarding headers. DRF cache throttles are non-atomic and provide only a baseline usage policy.

Ranked matchmaking, ranked guesses, and public leaderboard APIs remain unavailable. Party APIs and WebSockets are implemented below; the ranked WebSocket scaffold still rejects handshakes.

## Five-round singleplayer

All endpoints permit guests and use the existing cookie session. Mutations require CSRF even for anonymous requests. Ownership is checked for every round read/image/action; strangers receive 404. Responses are private/no-store and vary by Cookie. No client user/guest identifier, score, reveal percentage or timestamp is trusted.

| Method | Path                                                     | Result                                                                                                                             |
| ------ | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/games/singleplayer/current/`                       | `{round, session}` or both null; restores current round and score, never starts a game                                             |
| POST   | `/api/games/singleplayer/rounds/`                        | `{request_id: UUID}` → 201 five-round game; same request resumes latest round                                                      |
| GET    | `/api/games/singleplayer/rounds/<uuid>/`                 | Owned round plus its session summary                                                                                               |
| POST   | `/api/games/singleplayer/rounds/<uuid>/guesses/`         | `{request_id: UUID, guess: string}` → state plus `correct`, `incorrect`, `already_completed`                                       |
| POST   | `/api/games/singleplayer/rounds/<uuid>/forfeit/`         | Completes for zero points only after full 45-second reveal; result `forfeited` or `already_completed`                              |
| POST   | `/api/games/singleplayer/rounds/<uuid>/next/`            | `{request_id: UUID}` → activate next round only after completion; retries return current state; Round 5 returns `session_complete` |
| GET    | `/api/games/singleplayer/rounds/<uuid>/image/?v=<count>` | Authorized masked lossless WebP; `X-Revealed-Tiles` is server count; client v cannot advance reveal                                |

Round fields: opaque round `id`, `number`, `status` (`pending`, `active`, `solved`, `forfeited`, `expired`), `server_now`, nullable `started_at`/`reveal_finishes_at`/`expires_at`, `reveal_duration_seconds`, `grid_size`, `total_tiles`, `revealed_count`, `revealed_tiles` (revealed prefix only), `guess_count`, persisted `score`, server `available_points`, `can_forfeit`, authorized `image_url`, and `completion`. Pending rounds have no image URL, deadline or revealed tiles. Their image endpoint and game actions reject access.

Completion stays null until solved/forfeited, then contains only `answer`, `outcome`, `score`, `solved_in_seconds` (null for forfeits), `guesses`, `license`, `attribution`, and `category`. Synonyms, private storage paths/URLs, image IDs, descriptive filenames, seeds and future reveal order are never published.

Session fields: `id`, monotonically increasing `revision`, `status` (`active`, `complete`, `expired`), `server_now`, `expires_at`, `total_rounds` (5), `current_round_number`, `total_score`, `max_score` (5000), `solved_rounds`, and five `rounds` summaries. Summaries expose number/outcome; score is null until completion and answer is omitted until completion. The final summary remains immutable when another game starts.

Correct score is half-up rounding of `1000 * (1 - revealed_tiles / total_tiles) ** 2`, implemented with exact integer arithmetic. Points remain 0–1000; incorrect guesses never change stored scores. Full reveal does not end a round. Correct after full reveal is solved/0, forfeit is forfeited/0. Every completion and advance is serialized under the Match writer lock, which works with SQLite and PostgreSQL; repeated requests cannot award points twice.

Guesses: 1–120 characters; NFKC/casefold, whitespace collapse, punctuation/symbols as separators, apostrophes removed. Canonical answers and synonyms normalize identically. Punctuation-only guesses return 400. Request UUID conflicts return 409 `request_conflict`. Completed actions return `already_completed` without adding guesses or scores. An old completed-action retry after progression returns the current round to avoid reverting the UI.

Errors: 503 `library_empty` / `image_unavailable`; 409 `reveal_incomplete` before forfeit eligibility, `round_unfinished` for skipping, `round_not_current` / `round_not_started` for future rounds, `session_in_progress` for starting over while unfinished; 410 `round_expired` for expired/abandoned actions/images. Legacy one-round game mutations return 410 `legacy_session`; current-game recovery excludes legacy records. Account-owned active games can recover even when the browser lacks a round pointer; guests require their identity cookie.

Scoped baseline abuse limits remain CSRF 600/minute, starts/advances 30/minute, state/image reads 600/minute, and guesses/forfeits 600/minute. No per-round guess cap, incorrect penalty or gameplay cooldown is introduced.

## Multiplayer parties

All mutations require cookie-session CSRF, including guests. Member reads/actions/images are private/no-store and vary by Cookie. Codes are case-insensitive. Accounts use their server display name; guests supply `display_name` (2–24 letters/numbers/spaces/simple punctuation). Unknown/foreign membership is 404; closed/expired parties are 410; host violations are 403; gameplay conflicts are 409; active wrong-guess cooldown returns 429. No client identity, score, start time, or reveal count is trusted.

| Method | Path | Body / result |
| --- | --- | --- |
| POST | `/api/parties/` | `{request_id: UUID, display_name?: string, reveal_seconds?: 30, round_limit?: 10}` → 201 personalized state |
| GET | `/api/parties/<code>/` | Member state; refreshes presence as HTTP fallback |
| POST | `/api/parties/<code>/join/` | `{display_name?: string}` → member state; duplicate identity resumes |
| PATCH | `/api/parties/<code>/` | Host lobby settings: `reveal_seconds` (15/30/45/60), `round_limit` (5/10/15/20); extra fields rejected |
| POST | `/api/parties/<code>/start/` | Host + `{request_id: UUID}`; minimum two members |
| POST | `/api/parties/<code>/leave/` | Leaves, transfers host if needed; 204 |
| POST | `/api/parties/<code>/lobby/` | `{request_id: UUID}`; any member after final results may return everyone to lobby |
| POST | `/api/parties/<code>/guesses/` | `{round_id: UUID, guess: string, request_id: UUID}` → `{state, result}` |
| GET | `/api/parties/<code>/rounds/<uuid>/image/` | Authorized current masked WebP; client query parameters cannot advance reveal |

State contains `code`, `status` (lobby/playing/complete), `revision`, `server_now`, `expires_at`, `host_id`, `me_id`, two `settings`, active `members`, `match_id`, current `round`, `leaderboard`, `winners`, `message`, and fixed `rules`. It never exposes future round IDs/images, synonyms, original URLs, private filenames, or raw guesses.

Current round includes server start/deadline/next-transition timestamps, reveal size/count/prefix, private image endpoint, and private `me` solve/score/guess/cooldown state. `completion` remains null for everyone, including solved players, until round end; then it contains canonical answer and curated attribution/license/category. Leaderboard rows contain member ID/name, stored round/total score, solved/connected/left flags, round rank, and solved-round count. See [party rules and tie-breaking](parties.md).

`/ws/parties/<code>/` uses the same cookie identity and validates trusted origins before accepting. The server sends `{type: "state", state: ...}` initially and as state changes, with one-second reconciliation. Send `{type: "heartbeat"}` every five seconds. Guesses use `{type: "guess", round_id, guess, request_id}` and receive `{type: "guess_result", request_id, result, state}`; errors contain `type: "error"`, request ID where present, detail, code, and status. Lost acknowledgments may be retried over HTTP with the same UUID without repeating score effects. Unauthorized/session-revoked connections close with 4403; oversized frames close with 1009. Essential state survives connection/server/cache loss.

Party errors include `party_full`, `name_taken`, `match_started`, `settings_locked`, `not_enough_players`, `host_only`, `round_not_current`, `round_not_started`, `round_ended`, `already_solved`, `guess_cooldown`, `request_conflict`, and `party_closed`. Empty/unavailable curated libraries use the existing 503 game errors. Rejected deadline guesses still persist the deadline transition. No fuzzy matching or category selection is implemented.
