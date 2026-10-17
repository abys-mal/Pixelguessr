# Pixelguessr

Native moderation and player appeals are implemented at `/moderation` and
`/account-notices`. See [native moderation setup, access and workflows](docs/native-moderation.md).
See [current sanction effects and live enforcement](docs/moderation-enforcement.md).
See [Administrator Panel v1, API and launch instructions](docs/administrator-workspace.md).
Only administrators (active users with both `is_staff` and `is_superuser`) can enter Django Admin; moderators use the
native workspace with `moderation.access_workspace` permission.

A playable curated image-guessing game. React + TypeScript + Vite in `frontend/`; Django 5.2 LTS + DRF + Channels in `backend/`. Phase 4 runs locally with SQLite and in-memory services. PostgreSQL, Redis, and Docker configuration remain available for future use.

## Implemented

- Ranked Duel at `/ranked`: registered-only rating-based matchmaking, synchronized versus countdown, one guess per 45-second image, unlimited washes, first to four decisive wins, atomic Elo and final snapshots. Durable 30-second reconnect grace, immediate leave forfeits, coincidence-window No Contests, public profiles/history and paginated standings. See [rules, startup, configuration and two-account playtesting](docs/ranked.md).

- Real-time guest/account parties: six-character invites, up to 12 players, host-only 15/30/45/60-second reveals and 5/10/15/20-round matches. Shared countdowns, masked images, compact solved-player status during gameplay, full intermission/final standings, spectator states, automatic results/round transitions, and return-to-lobby replay. Host removal includes an accessible confirmation and optional party-specific identity ban. Guests receive automatic persistent party names. Brief disconnects retain membership for a 15-second presence lease; host departures close the lobby or abort the match, and fewer than two remaining players abort an active match. There is no host succession. Incorrect guesses cost 50 points with a server-enforced two-second cooldown. See [party operation and two-session test plan](docs/parties.md).

- Guest and account singleplayer at `/singleplayer`: exactly five sequential rounds with randomized 20×20 reveals over **45 seconds**, unlimited guesses without penalty/cooldown, canonical/synonym matching, and persisted progress/score. Correct guesses earn up to 1,000 points per round; totals are out of 5,000.
- Server-authoritative round state and reveal timing, durable session recovery, idempotent starts/submissions, 24-hour game expiry, private masked WebP frames, and explicit empty/loading/reconnect/error states. Raw originals and unrevealed answers/order never reach the client.
- Forfeit becomes available only after full reveal and awards zero points. Round results show the answer, outcome, points, and total; Next Round waits for the player. Round 5 opens Final Results with all scores/outcomes, solved count, Play Again, and Return Home.
- Four original CC0 illustrations, imported pending and explicitly reviewed only with `seed_dev_images --approve`. See [development image attribution](docs/development-images.md).
- Local JPG/JPEG imports use private WebP storage, an editable CSV manifest, content deduplication and explicit staff approval. See [local photograph import and verification](docs/local-image-imports.md).

- Responsive, dark-first homepage with Ranked Duel, Singleplayer, and Parties cards, mode rules, navigation, and accessible mobile layouts. All three modes open playable games. Ranked Duel requires a registered account.
- Custom UUID user model from the first migration; password validation; registration, login, logout, profile reads, and display-name edits. Same-origin cookie sessions with CSRF protection, including anonymous login and registration.
- Private curated image submissions by registered users: canonical answer, synonyms, category, source, license, attribution, external HTTPS references or validated uploads. Six initial categories are installed by migration. All submissions begin pending. Users can see only their own submissions.
- Still JPEG/PNG/WebP validation (8 MB, 64–4096 px, 12 MP), re-encoding to WebP, stripped metadata, opaque UUID filenames, private local or S3-compatible storage, and an authenticated administrator-only preview. The server never fetches a submitted URL.
- Django Admin review/approval/rejection, reports, sanctions, and staff-verified Pro/Master/Legend titles. Warning acknowledgment works in account settings. Warnings expire after 90 days. Probation blocks ranked entry and submissions. Suspension/closure invalidate existing sessions, including staff sessions. Only superusers can reverse closure through Admin.
- Answer-safe public catalog metadata, mode rules API, liveness/readiness, database migrations, dependency locks, formatting/linting, regression tests, and CI with PostgreSQL and Redis.

## Ranked and deferred work

- Registered-only ranked matchmaking, first-to-four decisive wins, atomic Elo, public profiles, history and paginated standings are implemented. See [ranked operation and playtest checklist](docs/ranked.md). Guests remain separate from user accounts.
- ASGI and Channels/Redis routing. `/ws/parties/<code>/` provides real party sessions; `/ws/matches/<uuid>/` provides private ranked sessions, with `/ws/ranked/queue/<ticket>/` for matchmaking. `/api/modes/` reports all three modes available.
- Public Elo, derived tiers, wins/losses/rated counts and completed ranked history. Leaderboards require at least one rated match; No Contests do not qualify.
- Future phases: production load testing and operations, matchmaking throughput and image-compositor optimization.
- Username/email/password changes and sanction appeals are implemented. Later account work: email verification, password recovery, and operational production deployment. No party chat is planned for V1.

## Start locally without Docker

Prerequisites: Python 3.13, Node 22.12+ (Node 24 recommended). In PowerShell, from `C:/Users/actian/source/Pixelguessr`:

```powershell
python scripts/setup_env.py --lite
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
cd backend
..\.venv\Scripts\python.exe manage.py migrate
# Optional: explicitly import and review only the four original development fixtures.
..\.venv\Scripts\python.exe manage.py seed_dev_images --approve
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

In another terminal from the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

For parties, keep a third terminal running from the repository root:

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py party_clock
```

This advances deadlines and expiry even when every browser disconnects. State/image requests and WebSocket snapshots also reconcile elapsed deadlines, so server restarts retain the original timeline. The clock stores essential state in SQLite; it does not require Redis.

Open http://localhost:5173. Vite proxies `/api` and `/ws` to Django; this preserves same-origin cookies and avoids unnecessary CORS configuration. Do not substitute a different frontend port without updating the CSRF origins.

Existing `.venv`, `.env`, and `frontend/node_modules` are already prepared in this local checkout; installation commands are needed only for a fresh setup.

The lightweight mode is explicitly development-only: `DEBUG=True`, `USE_SQLITE=True`, `LOCAL_SERVICES=True`. The environment helper preserves an existing `.env`; edit those flags yourself if switching modes. To use real services locally, start `docker compose up -d db redis`, set both fallback flags to `False`, and keep the default localhost database/Redis URLs. SQLite and PostgreSQL are separate databases; switching does not copy data. On macOS/Linux use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.

Run a fourth terminal for durable ranked deadlines (in addition to the existing party clock):

```powershell
cd "C:/Users/actian/source/Pixelguessr/backend"
..\.venv\Scripts\python.exe manage.py ranked_clock
```

## Local checks

From the repository root:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m ruff format --check .
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
cd ../frontend
npm run lint
npm run format:check
npm test
npm run build
```

Tests use an isolated in-memory SQLite database and in-memory cache by default; never your development data. CI supplies `TEST_DATABASE_URL` and `TEST_REDIS_URL` to exercise PostgreSQL and an isolated Redis database. Backend tests additionally cover party permissions, capacity, kick/identity bans, departure/grace/abort races, WebSocket origin/session authorization, shared reveals, persisted cooldowns, negative scores, deadline progression, replay, and concurrent mutations. Backend tests cover guest/account gameplay, CSRF and ownership, normalized synonyms, pixel-level reveal security/timing, guessing after full reveal, retries/expiry, snapshots, missing storage, and explicit fixture review, alongside the existing foundation regressions. Frontend tests cover gameplay, refresh, recovery, completion, empty/expired rounds, stale polling, availability, routing, and CSRF transport.

Upload tests use the built-in pytest `tmp_path` fixture. Pytest creates and manages temporary directories under the operating system temporary location on Windows and Linux; no custom base-temp directory or pre-existing `.pytest_cache` folder is required.

Formatting: `python -m ruff format .` in backend; `npm run format` in frontend. Runtime dependencies are pinned in `backend/requirements.txt`, development tools in `requirements-dev.txt`, and npm resolutions in `frontend/package-lock.json`. `.in` files describe upgrade ranges; regenerate Python pins in a clean environment and test before updating.

## Staff and storage

Create a superuser, log into Django Admin, and open Image submissions. Inspect metadata and the private upload preview (or the external reference), then approve/reject. Public responses never contain answers, filenames, external image URLs, provenance URLs, or attribution that could reveal an answer. Attribution is retained privately for a future post-round disclosure API; the actual license must permit this game’s use before staff publish anything. Do not expose the private-media directory from a web server.

For S3-compatible hosted storage, set `USE_S3=True`, `S3_BUCKET_NAME`, and `S3_REGION_NAME`. Set `S3_ENDPOINT_URL` for a compatible provider. Use IAM workload credentials where available, or the optional `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` environment variables. Keep bucket public access blocked; there is no public ACL or public media route. Staff previews stream through authorized Django views. Changing storage does not migrate existing files. An actual bucket connection requires your infrastructure/credentials and is not covered by local tests.

Sanctions may be issued independently without escalation. Moderators use the [native workspace](docs/native-moderation.md) to issue, reverse or replace sanctions and review player appeals. Only administrators can enter Django Admin, manage access, moderate staff or reverse closures. Original sanction records remain intact; replacements are linked records. Reports require an authenticated account; guest reporting is deferred. The [older Admin audit checklist](docs/moderation-audit.md) retains historical verification context; the native workspace guide contains current roles and workflows. Profile Sign Out uses the existing CSRF-protected logout endpoint and also works after session expiry. New titles can supersede an existing verified title and are not derived automatically from rating.

## Before production

Set `DEBUG=False`, a unique random secret of at least 50 characters, exact `ALLOWED_HOSTS` and HTTPS `CSRF_TRUSTED_ORIGINS`, PostgreSQL, and Redis. In-memory fallbacks are rejected outside debug mode. Secure cookies, HTTPS redirect, HSTS, clickjacking protection, and content-type protection are configured. Run `python manage.py check --deploy`. Serve the built React output with history fallback and proxy `/api`, `/admin`, and `/ws`; collect and serve Admin static assets separately. Use Daphne against `config.asgi:application`; run migrations as a release step rather than per-worker startup. Terminate TLS at a trusted edge; configure the proxy SSL header only when that edge strips untrusted client values.

Application throttles are a baseline usage policy, not a distributed atomic brute-force or DDoS defense. Add edge rate limits, a 10 MB request-body limit, trusted proxy IP handling, durable backups, upload quotas/cleanup, monitoring, secure staff access, and email verification/recovery before public launch. Keep PostgreSQL, Redis, secrets, and private storage off public networks. Production-oriented foundation does not mean production deployment is finished.

See `docs/architecture.md` and `docs/api.md` for the boundaries and Phase 2 contracts.

## Future full-stack infrastructure (optional)

Prerequisites: Docker Engine/Desktop with Compose v2. From the repository root:

```powershell
python scripts/setup_env.py
docker compose up --build
```

Open http://localhost:5173. API liveness: http://localhost:8000/api/health/live/. Admin: http://localhost:8000/admin/.

```powershell
docker compose exec backend python manage.py createsuperuser
docker compose exec backend pytest -q
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run format:check
docker compose exec frontend npm run build
```

Compose runs migrations automatically before starting the ASGI development server and waits for database, cache, and API readiness. Code is mounted for reload. Services bind only to loopback. The Dockerfiles/Compose are development infrastructure; deployment needs a production edge and static asset serving. `docker compose down` stops services without deleting persistent volumes. If dependency locks change, rebuild images and renew the frontend anonymous/named modules volume as appropriate.

## Singleplayer configuration and limits

New rounds snapshot `SINGLEPLAYER_GRID_SIZE` (default 20, allowed 5–40), a fixed 45-second reveal duration, and `SINGLEPLAYER_ROUND_TTL_SECONDS` (default 86400, longer than the reveal). Existing rounds retain their settings. Guest identity and browser session last seven days; active five-round games expire after 24 hours. Clearing cookies or signing out removes the browser's recovery pointer; private rounds cannot be recovered from a UUID alone.

The client requests state about once per second and crossfades only server-confirmed tiles. Django composes private lossless WebP frames on demand at 960×720 with letterboxing. Reusable services keep timing/answers/ownership separate from delivery, but concurrent multiplayer needs shared state transport, load testing, edge controls, and a more efficient compositor before launch. Baseline abuse limits (600 guesses/minute) impose no gameplay cooldown or per-round guess limit.

Only approved **hosted uploads** are playable. Approved external references remain metadata until staff import a licensed file through the normal private storage pipeline; gameplay never fetches remote URLs. Solved and forfeited rounds disclose the canonical answer and credit; synonyms and private storage remain hidden. Original development artwork is a small test library, not a finished content collection.

## Five-round scoring and integrity

Points for a correct guess are `round_half_up(1000 * (1 - r) ** 2)`, where `r` is **server-revealed tile count / total tiles** at acceptance. Integer arithmetic implements half-up rounding consistently: 0%, 10%, 25%, 50%, 75%, and 100% award 1000, 810, 563, 250, 63, and 0 points. Wrong guesses never alter stored scores. A correct guess after 45 seconds is recorded as solved with zero points; forfeit is recorded separately with zero points. The interface shows only cumulative earned points and completed round scores; there is no live potential-score counter.

A Match stores the five-round limit, game expiry, and revision; Round stores ordering/outcome/timing/private image snapshots; RoundPlayerState stores points; Participant stores their sum. Five rounds are created up front but only one starts at a time. Future images cannot be delivered or guessed. Next Round requires a completed current round. Duplicate/concurrent requests acquire a match writer lock before mutable reads and cannot score or advance twice. Starting a different game while one is unfinished returns 409; retries of the same start safely resume progress.

Image selection uses distinct approved hosted images until the library is exhausted, then chooses least-used images while avoiding immediate repeats whenever possible. Pending rounds recheck staff approval and select an eligible image when activated. A missing/empty library at activation leaves the completed result available for retry; no moderation status is changed.

Additive migrations `games.0003` and `games.0004` retain prior one-round games as read-only history. They preserve original scores, timestamps, reveal durations, image records/files and owners; completed legacy outcomes are backfilled without inventing scores. The new game page starts a five-round game instead of extending or replaying legacy results.

### Real SQLite concurrency checks

The normal suite uses isolated in-memory SQLite. Concurrency cases intentionally skip there because shared in-memory SQLite has different lock behavior. From `backend/`, run them against a **disposable** file database (never `db.sqlite3`):

```powershell
$env:TEST_SQLITE_FILE = Join-Path (Get-Location) '.pytest_cache/phase21-concurrency.sqlite3'
..\.venv\Scripts\python.exe -m pytest -q -k concurrent
Remove-Item Env:TEST_SQLITE_FILE
```

The optional `TEST_SQLITE_FILE` affects only test settings. PostgreSQL CI settings are preserved. Migration compatibility is exercised on an isolated test database, not the development database.
