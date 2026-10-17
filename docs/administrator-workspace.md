# Administrator Panel v1

The administrator panel extends the existing `/moderation` workspace. Home,
Players, Reports and Appeals remain available to native moderators. Administration
navigation and Django Admin require an active account with **both** `is_staff` and
`is_superuser`. These checks run on the server and in mutation services; browser
navigation is not an authorization boundary. Closed/suspended accounts remain
subject to existing session and account restrictions.

## Sections and routes

| Page | URL | Behavior |
| --- | --- | --- |
| Overview | `/moderation/administration` | Database counts, needs-attention links, latest eight audit events, bounded health probes |
| Image Library | `/moderation/administration/images` | Search, status filters, 24-image pages, selection, private detail drawer, editing, review, retirement and reveal preview |
| Image Imports | `/moderation/administration/imports` | Persistent preparation batches; resume at `/imports/<batch-id>` |
| Staff & Roles | `/moderation/administration/staff` | Staff-only directory, role filters, separate ordinary-player search, explicit moderator grant/removal confirmation |
| Audit Log | `/moderation/administration/audit` | Read-only search, action/target filters, before/after details and pagination |
| System Health | `/moderation/administration/health` | Read-only bounded database, Redis and storage checks |

Home contains the persistent staff announcement. Moderators see only published,
unexpired content; administrators can edit drafts, publish/unpublish and set an
expiry. Content renders as plain text. Version checks reject stale saves.

Existing player details at `/moderation/players/<id>` add administrator controls:

- **Elo override:** integer from the configured rating floor (normally 100) through
  2,147,483,647, with an optional reason. Updates the authoritative rating and any
  queued rating snapshot. Tiers remain derived from Elo. An active ranked duel
  must finish first; historical matches and rating snapshots are preserved.
- **Reopen account:** offers an optional reason and requires confirmation showing the original
  closure reasons. Reverses active closure sanctions through existing services,
  preserves their records and unrelated sanctions, and adds a safe player notice.
- **Honorary title:** exactly PRO, MASTER or LEGEND; assignment replaces the single
  existing verified title, and removal revokes it. Shared identity rendering puts
  the badge before the player name. Competitive tiers stay in profile statistics
  and the separate leaderboard tier column.

## Images and imports

Choose or drop multiple still JPG, PNG or WebP files. Uploads use the shared image
conversion/storage pipeline: 8 MiB input maximum, at least 64 pixels per side,
existing dimension/pixel checks, bounded resize, stripped metadata, private WebP
files, opaque keys and content deduplication. Nothing fetches external URLs.

Each file has a persistent batch item with uploaded/duplicate/failed status.
Request UUIDs make upload retries idempotent. Duplicate files reuse their existing
image without overwriting reviewed labels. Invalid files produce individual
errors. A storage/database failure can require retrying the file; new storage
objects are cleaned up if the batch transaction fails. Unsent browser selections
are not persisted; uploaded items and their labels survive leaving the page.

New images start pending with unverified labels. Open **Prepare labels**, enter
answers/synonyms/category, and **Save reviewed labels**. This explicitly records
label review; it does not approve the image. The library then provides individual
or selected-image approval, rejection with an optional reason, retirement and
restoration. Bulk actions validate each unique ID independently (maximum 50),
commit each successful item, and report success, skipped or failed per image.

The existing development Pexels policy is preserved: generic `Pexels` attribution,
`Pexels License`, optional individual source metadata while
`PEXELS_PROTOTYPE_METADATA=True` and `DEBUG=True`. Provenance remains stored for
later enrichment. Approval still verifies labels, stored bytes and all existing
model rules. The provisional canal photograph remains pending until its label is
explicitly reviewed. Browser imports are intended for this curated prototype;
production provenance/licensing rules remain stricter when that flag is off.

The drawer uses the real server-side reveal compositor with a stable tile order
and a 20 by 20 inspection grid. Originals and preview frames require administrator
authorization and are not publicly cached. Progressive gameplay endpoints retain
their existing masking/ownership rules. Private storage must never be web-served.

Retirement is separate from rejection: files and historical references remain,
while future selection and the public catalog exclude retired images. Existing
round answer/image snapshots are preserved. Retiring the last playable image is
refused while games are active; restore an approved image to resume selection.

Historical command-line imports remain available in the library. Their CSV files
are not exposed as browser batches or modified by browser preparation. Use the
[local import guide](local-image-imports.md) for that workflow.

## API

All paths below are relative to `/api/moderation/workspace/administration/`.
GETs are paginated at 24 rows where applicable. Writes use existing session
cookies, CSRF and server input validation. Unknown mutation fields are rejected.

| Path | Methods | Purpose |
| --- | --- | --- |
| root | GET | Overview metrics and health |
| `staff/?role=all` | GET | Role-filtered staff directory |
| `players/?q=<username>` | GET | Separate ordinary-player search |
| `players/<uuid>/` | POST | `operation`: `rating`, `reopen`, `title`, `moderator` |
| `announcement/` | GET, POST | Staff read; administrator write with version |
| `audit/?q=&action=&target_type=&page=` | GET | Existing Activity log |
| `health/` | GET | Safe probe results |
| `images/?q=&status=&page=` | GET | Library |
| `images/<uuid>/` | GET, POST | Detail / reviewed labels |
| `images/review/` | POST | `ids`, `operation`, `reason` |
| `images/<uuid>/preview/?reveal=200` | GET | Private original or actual reveal frame (0–400 tiles) |
| `imports/` | GET, POST | List/create named batches |
| `imports/<uuid>/` | GET, POST | Item list / multipart `file` and unique `request_id` |

The announcement GET is intentionally available to moderators; every other
administration endpoint requires administrator access. Native moderator promotion
only grants `moderation.access_workspace`, never Django flags. Administrator flag
assignment/removal stays CLI-only, including read-only flag fields and guards in
Django Admin. Existing protected-account moderation rules remain in force.

## Models, audit and operations

- `library.0005_administrator_workspace` adds `retired_at`, `retired_by` and
  `review_reason` to ImageSubmission; creates ImportBatch and ImportItem with
  unique request IDs and protected references.
- `moderation.0004_administrator_workspace` extends Activity with optional player
  linkage, stable target type/ID, reason and an action/time index; creates the
  singleton StaffAnnouncement with editor, expiry and optimistic version.
- Existing VerifiedTitle is reused. No competing title or audit table is added.

Administrative mutations audit actor, target, timestamp, relevant before/after
values and any optional routine reasons. Pixelguessr exposes no audit write/delete endpoint.
Passwords, session tokens and environment configuration are not audit payloads.
Transactions and the existing ranked/player writer ordering protect multi-record
changes; image reviews return explicit per-item outcomes.

Health uses worker-bounded probes with 1.5-second result waits and one-second
Redis network timeouts. Database executes SELECT 1; storage reads a small prefix
of one existing hosted image, not a full integrity scan or write test. Backend
Healthy means the authenticated request is executing. Unconfigured Redis/local
services and unavailable recent-error collection show **Not Configured**.
No error telemetry is fabricated, and no raw diagnostics or operational controls
are exposed. Real Redis, PostgreSQL, S3 and production load testing require those
services; local verification uses SQLite, private local storage and memory cache.

## Local launch and verification (Windows)

The existing `.env`, `.venv`, frontend dependencies and collection are retained.
No seeding or database reset is needed for this panel. From PowerShell:

```powershell
Set-Location 'C:\Users\actian\source\Pixelguessr'
.\.venv\Scripts\python.exe backend/manage.py migrate
.\.venv\Scripts\python.exe backend/manage.py check
```

For a fresh development administrator, run `createsuperuser` from this directory:

```powershell
.\.venv\Scripts\python.exe backend/manage.py createsuperuser
```

Existing account flags may be changed only through a trusted Django shell/CLI.
No account promotion is performed by migrations. Use your own local credentials;
automated browser verification used a separate fixture database and media copy.

Run each command below in its own terminal, from the repository root:

```powershell
# Terminal 1 — Django
.\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8000

# Terminal 2 — frontend (Node installation path only if npm is absent from PATH)
$env:Path = 'C:\Program Files\nodejs;' + $env:Path
Set-Location frontend
npm run dev

# Terminal 3 — party deadlines
.\.venv\Scripts\python.exe backend/manage.py party_clock

# Terminal 4 — ranked deadlines
.\.venv\Scripts\python.exe backend/manage.py ranked_clock
```

Open `http://127.0.0.1:5173/login`, sign in, then visit
`http://127.0.0.1:5173/moderation/administration`. The existing `.env` allows the
5173 localhost/127.0.0.1 origins. If choosing another frontend port, add that exact
origin to CSRF_TRUSTED_ORIGINS and restart Django. Restart an already-running
backend after migration to load the new models/routes.

From `backend/`, run checks using the project interpreter:
`..\.venv\Scripts\python.exe -m pytest -q`, Ruff check/format checks, and
`..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`.
From `frontend/`, run `npm test`, `npm run lint`, `npm run format:check` and
`npm run build` (includes TypeScript). Tests use isolated databases and temporary
media. Verify admin navigation, a moderator's denied direct admin route, pending
upload preparation, review outcomes, announcement visibility and mobile layouts.


## Workspace quality and staff self-action rules

Overview uses a single responsive grid with shared section spacing. Metric cards
have matching padding and heights; the activity/status panels align in two columns
and stack on small screens. The image metric reads **Approved images** with an
explicit explanation that retired entries and records without hosted files are
excluded. Backend statuses and game-selection rules are unchanged.

Staff & Roles presents **Promote a Player** above **Current Staff**. The latter is
a compact, role-filtered list with identity, account status and management actions.
Assignment dates/recent activity remain available under Role history. Ordinary
players only appear in the separate promotion lookup. Inactive, closed, suspended
and probation statuses are reported explicitly.

Moderator-removal controls use explicit backend eligibility. Accounts carrying
Django staff/superuser flags, including the current administrator, cannot be
managed through either moderator-management API. Both flags remain CLI-only.

Staff cannot impose or replace a sanction on their own account. The native service
checks before changing an original sanction, and shared model validation also
covers Django Admin creation and punitive changes to existing records. Moderators
remain unable to sanction protected staff; administrators may sanction other staff.
Legacy records remain readable/acknowledgeable, and ordinary profile edits remain
available. Django Admin excludes the actor from sanction targets and makes their
own active-account flag read-only with a server-side self-deactivation guard.
No migrations or changes to existing data are required for these rules.


For voluntary closure, verified permanent erasure, and CLI password reset, see
[account lifecycle and data retention](account-lifecycle.md). Permanent erasure
is a sensitive new tool and always requires a reason and password verification.
