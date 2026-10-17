# Moderation and quality-of-life update

## Player information and account controls

The staff player detail API adds only selected non-sensitive fields: stored identity,
full UUID, exact ISO creation timestamp, status from current sanctions/active flag,
assigned role and existing ranked counters. It does not expose email, hashes, tokens,
IP addresses or sessions. The Player Information section is available wherever staff
may already review that player; protected-account visibility rules remain unchanged.
UUID copying reports success or a selectable-text fallback. The permanent account
delete button now shares the existing action-row gap, wrapping and button metrics.
Its confirmation, password/reason requirements and eligibility are unchanged.

## Public player reports

A signed-in player can open Report from another player's public profile. The
warning-triangle action opens the shared keyboard-accessible modal. The existing
`POST /api/moderation/reports/` accepts `subject`, `category` and `details`. A written
reason of 1–2000 non-whitespace characters is required for every report category,
including Other. Other remains an existing category for optional sanction context.
Categories are shared by the two frontend selection interfaces.

The endpoint validates identity/category and rejects self-reporting, missing targets,
unknown fields and attempted reporter/resolution injection. Reporter identity always
comes from the authenticated session. The existing report throttle is 10 requests
per day. A serialized service also rejects duplicate unresolved reports for the same
reporter, target and category within 24 hours. Invalid submissions consume the normal
request throttle. Reports enter the existing staff queue and audit timeline, without
creating any player-visible sanction or report notice for the target.

## Appeal decisions

Both Uphold and Reverse can include `closing_reason` at the existing staff decision
endpoint. The optional text is limited to 2000 characters, stored on Appeal and
recorded in the decision audit event. Empty reasons remain empty and produce no
empty explanation block. The appealing player's existing notices endpoint returns
the reason, while internal staff notes remain private. React renders the reason as
text, preserving line breaks without interpreting HTML. Existing authorization,
reversal behavior, duplicate-decision rejection and notifications remain in place.

## Sign out

AuthProvider clears the session state and replaces the current route with `/` after
a successful ordinary logout. Failed requests preserve authentication and show the
existing error. In-flight session refreshes remain protected by the existing session
generation check. The voluntary closure flow still uses its separate completion page.

## Permanent library-image deletion

Only active administrators can post `{ "confirm": true }` to
`/api/moderation/workspace/administration/images/<uuid>/delete/`. Both the grid and
image drawer offer the small red trash action only for rejected or retired images.
Pending and active approved images are rejected server-side. No written reason is
required. The confirmation names the exact image/UUID and explains irreversibility.

The transaction removes the library record and dependent ImportItems, preserving
batches, unrelated images, rounds, matches, outcomes, guesses, scores and players.
Round image references detach; existing answer snapshots remain. Required attribution,
license and category are copied into a minimal JSON snapshot for completed results.
Original image bytes are not retained for historical viewing. Future selection uses
the existing eligibility rules and cannot select a deleted record.

An image still used by a currently revealing round cannot be deleted until that
round ends. Retired images reserved by future unstarted rounds may detach; normal
activation reselects an eligible image. A shared file remains stored when another
image or round needs it. No game scoring or reveal rules are changed.

A minimal `image_permanently_deleted` Activity retains actor, timestamp, image UUID
and deleted outcome, without image bytes, filenames or an unnecessary answer copy.
Private file cleanup uses the existing durable PendingFileDeletion queue after
commit, including retry on storage failures. The source-compositor cache is evicted
for the removed file. Use the existing command to retry pending cleanup jobs:

```powershell
.\.venv\Scripts\python.exe backend/manage.py cleanup_deleted_files --limit 100
```

## Migrations and verification

- `moderation.0006_moderation_qol`: blank optional Appeal.closing_reason.
- `games.0009_moderation_qol`: empty-by-default Round.image_metadata_snapshot.

Neither migration deletes or rewrites player/game/image data. Back up the database,
apply with the project .venv interpreter, and restart Django and clock workers:

```powershell
.\.venv\Scripts\python.exe backend/manage.py migrate
.\.venv\Scripts\python.exe backend/manage.py check
```

Tests use isolated SQLite and temporary private storage. Browser fixtures use
synthetic accounts and generated images. Actual permanent deletion is verified in
automated backend tests; browser dialogs are inspected and cancelled. No real
accounts or library images are deleted during verification. Remote storage behavior
is exercised through the shared cleanup abstractions and simulated failures;
production services and infrastructure backups retain separate operational policies.
