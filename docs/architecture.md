# Architecture

One Django application, one React application, PostgreSQL, and Redis. No microservices or background worker are necessary for Phase 1.

```text
Browser → Vite development proxy / production edge → Django ASGI
                                                    ├─ HTTP /api + /admin
                                                    ├─ Channels routing (currently rejects matches)
                                                    ├─ PostgreSQL: durable domain data
                                                    ├─ Redis: shared cache/throttles + channel layer
                                                    └─ Private filesystem / S3: normalized uploads
```

## Responsibility boundaries

| Backend app | Responsibility |
| --- | --- |
| accounts | Custom users, public/private serializers, sessions, account permissions, verified titles |
| library | Category and submission persistence, validated upload pipeline, private references, staff review |
| moderation | Reports, audited sanctions, active restriction policy, warning acknowledgment |
| games | Game rules, persistence scaffold, unavailable mode API, rejecting WebSocket route |
| core | Minimal liveness and database/cache readiness |
| config | Settings, environment, URL/ASGI wiring |

React uses route-level pages, reusable panels/badges/status messages, one session context, and one CSRF-aware API helper. CSS variables, shared layout classes, and breakpoints support desktop/mobile. Forms call actual APIs; other pages explicitly describe future functionality. The decorative reveal illustration is static and labeled as a visual concept.

## Data and trust

User UUIDs are established in the first migration. Username/email uniqueness is case-insensitive at both validation and database levels. Public profiles omit email and provisional ratings. Clients cannot edit staff status, tiers, titles, or ratings.

Submissions require exactly one image reference. Uploaded filenames are opaque, files are normalized, and external URLs are stored without fetching. The public catalog is an explicit minimal allowlist of ID, category, and creation time. A submitted image is private until reviewed; even approved raw storage references remain private in Phase 1. Review requires staff identity and a timestamp. Staff previews have no-store caching and authorization on every request.

GuestIdentity does not authenticate today. In Phase 2 its random identifier must be bound to a signed server session, expire, and be checked on every party action. Never accept a client-provided user/guest ID as authentication.

Participant enforces exactly one account or guest and uniqueness within a match. RoundPlayerState holds signed round scores, solve time (spectator state), and cooldown. Participant holds a nonnegative cumulative score. Guess sequence is unique per round/player. Ranked mode’s one-guess limit and membership checks are represented in model `clean()`; Django does not call `clean()` on arbitrary `save()`/`objects.create()`. Phase 2 services must validate and lock rows in transactions; no write gameplay endpoints are exposed now.

Moderation checks start times, expiry, and audited revocation. Warnings remain active after acknowledgment until their 90-day expiry or revocation, but acknowledgment lifts the warning gate. Probation disables submissions and will disable ranked when matchmaking exists. Suspension/closure deny authentication and retrieval of existing session users via the custom auth backend. Admin prevents deletion or editing of issued sanctions and requires superuser status to reverse closure.

## Phase 2 implementation contract

- The server creates a private reveal order and authoritative start/deadline. It controls randomness, reveal progress, correctness, cooldowns, scores, spectators, wins, and final Elo.
- Publish only opaque image-delivery tokens, revealed tile coordinates, public participant summaries, authoritative deadlines, and game state. Do not send canonical answers, synonyms, private storage references, or revealing attribution/provenance until an intentional post-round disclosure.
- Prevent downloading the full image at the start of a competitive round. Implement authorized tile delivery or rendered progressive images; a client-side cover over a full image is insufficient.
- Validate account restrictions, match membership, round state, and guess limits inside atomic services. Use row locks/idempotency to decide concurrent guesses and apply Elo once after match completion. Redis is transient transport; PostgreSQL is the durable source of truth.
- Singleplayer: unlimited guesses, no cooldown/penalty, image stays after 30 seconds until solved.
- Parties: unlimited guesses, incorrect penalty 50 and cooldown 2 seconds, up to 1,000 points based on reveal progress. Signed round score, cumulative floor zero, solved players spectate, everyone solved ends early.
- Ranked: accounts only, matchmaking only, one guess each, wrong guess immediately loses, first correct wins, no winner replays, first four decisive wins ends the match. No tier thresholds have been selected.
- Authentication of Channels sessions and origin checking are wired; implement object-level authorization, reconnect state, message validation, and distributed timing before accepting any game socket.

## Verification scope

Local regression tests use SQLite/in-memory services; CI is configured for PostgreSQL/Redis. Compose configuration validation runs in CI. Private S3 connectivity and deployment-specific proxy/TLS/storage policy require integration verification in the deployment environment. No gameplay correctness claim is made by Phase 1 tests.
