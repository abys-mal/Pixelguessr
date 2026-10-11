# Phase 2 API

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
| GET    | `/api/modes/`                                   | Public intended rules; gameplay_available=true; only singleplayer available=true              |

Standard paginated result: `{count, next, previous, results}` (24 per page). Validation failures are 400, denied session permissions 403, unknown objects 404, and throttled requests 429. Login failure has a generic error; production should add edge abuse controls. CSRF failure may use Django’s HTML error body; the frontend never displays raw HTML.

Submission fields: `canonical_answer` (120 chars), `accepted_synonyms` (JSON list, max 30 strings of 120 chars), `category` (integer ID), `source` (`commons`, `licensed`, `ai`, `manual`), `source_url` (HTTPS provenance required for commons/licensed), `license` (160 chars), `attribution` (500 chars), and exactly one of `external_image_url` or `image_file`. With multipart, encode accepted_synonyms as a JSON string. Upload limits: 8 MB, still JPEG/PNG/WebP, minimum 64 px per side, maximum 4096 px per side and 12 MP. Client-supplied status, reviewer, owner, and storage keys are never accepted as writable fields. Public catalog output includes only `id`, nested category metadata, and `created_at`.

Throttle scopes: anonymous 120/hour, user 1200/hour, login/register 10/minute, image creation 20/day, reports 10/day. Scoped endpoints use their scope rather than both generic scopes. Configure trusted proxy count according to real infrastructure; the default trusts no forwarding headers. DRF cache throttles are non-atomic and provide only a baseline usage policy.

Party creation/join, matchmaking, ranked guesses, and leaderboard APIs remain unavailable. The prepared multiplayer WebSocket route rejects all handshakes.

## Singleplayer

All endpoints permit guests. Mutations require CSRF even when anonymous. Reads and mutations require the session owning the round (or the participant account); strangers receive 404. Responses use `Cache-Control: private, no-store` and `Vary: Cookie`.

| Method | Path                                                     | Result                                                                                                                                      |
| ------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/games/singleplayer/current/`                       | `{round: null}` or latest session round snapshot                                                                                            |
| POST   | `/api/games/singleplayer/rounds/`                        | `{request_id: UUID}` → 201 `{round: ...}`; same request/session resumes original round                                                      |
| GET    | `/api/games/singleplayer/rounds/<uuid>/`                 | Owned round snapshot                                                                                                                        |
| POST   | `/api/games/singleplayer/rounds/<uuid>/guesses/`         | `{request_id: UUID, guess: string}` → `{round, result}` with `correct`, `incorrect`, or `already_solved`                                    |
| GET    | `/api/games/singleplayer/rounds/<uuid>/image/?v=<count>` | Authorized lossless masked WebP; `X-Revealed-Tiles` reports authoritative count. `v` is only a client frame version; cannot advance timing. |

Snapshots contain `id`, `status` (`active`, `solved`, `expired`), `server_now`, `started_at`, `reveal_finishes_at`, `expires_at`, `grid_size`, `total_tiles`, `revealed_count`, `revealed_tiles` (already revealed prefix only), `guess_count`, private round `image_url`, and `completion` (null until solved). Completion contains only `answer`, `solved_in_seconds`, `guesses`, `license`, `attribution`, and `category`. No synonyms, source/private storage URLs, image IDs, filenames, seed, or remaining reveal order are exposed.

Guesses: 1–120 characters, Unicode NFKC + casefold, collapsed whitespace, punctuation/symbols treated as separators, apostrophes removed. Canonical answer and curated synonyms are normalized identically. Punctuation-only guesses are 400. A reused request ID with a different guess/round is 409 `request_conflict`. Repeating an accepted submission does not add another guess. Submitting after solve returns the completed snapshot without adding a guess.

Empty approved hosted library: 503 `library_empty`; inaccessible stored image: 503 `image_unavailable`; expired/abandoned guess: 410 `round_expired` with expired snapshot; expired image: 410. Full reveal after 30 seconds remains `active`, accepting guesses without penalty/cooldown. Session-bound guests cannot regain rounds after cookie loss. New starts abandon the previous active session round.

Scoped baseline abuse limits: CSRF 600/minute, starts 30/minute, state/image reads 600/minute, guesses 600/minute. Generic 120/hour anonymous limits do not apply to these game scopes. There is no per-round guess cap or gameplay cooldown. These cache-based safeguards are not a production concurrency or edge-abuse solution.
