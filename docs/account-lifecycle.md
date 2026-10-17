# Account lifecycle and data retention

Routine existing administrator actions accept omitted reasons; optional context is
still audited. This applies to the existing image, role, rating, title, reopening,
announcement and sanction tools only. Moderator requirements and protected-account
rules are unchanged. It is not an exemption for future administrative tools.
Moderation category `other` is available alongside all existing categories, and
sanction context remains optional. Public player reports require a written reason
for every category; see [moderation quality-of-life changes](moderation-qol.md).

## Voluntary closure

The muted **Close account** link at the bottom of Account Settings opens
`/settings/close-account`: Understand, Verify current password, Confirm with exact
`CLOSE MY ACCOUNT`. Back and Cancel clear the retained in-memory password. No
password is put in URLs, browser storage or audit events. The final request checks
the password again and derives the target solely from the authenticated session.
Both password endpoints require CSRF and use the existing account-change throttle.

`POST /api/auth/verify-closure-password/` verifies `current_password`;
`POST /api/auth/close-account/` also requires `confirmation`. Unknown fields are
rejected. Closure creates an ordinary closed Sanction with explicit
`origin=voluntary`, a non-disciplinary explanation and a `voluntary_closure` audit
event. Existing records default to `disciplinary`. Staff sanction tools cannot
submit this origin or bypass self-sanction restrictions.

Closure preserves data, other sanctions and approved images, invalidates all
stored sessions, signs the player out and prevents normal login/gameplay. An
administrator can use the existing reopening workflow; independent sanctions
remain effective. The existing authentication implementation uses database
sessions, not persistent API tokens.

## Permanent deletion

The administrator player controls expose a separate danger dialog only for a
closed, unprotected account other than the actor. The server independently checks
fresh actor and target rows under the existing writer gate. Both administrator
flags and an active, unrestricted actor are required. A currently effective
closed sanction is mandatory; inactivity, suspension or probation alone do not
qualify. All staff flags and direct/group moderation permissions protect targets.

`POST /api/moderation/workspace/administration/players/<uuid>/delete/` requires
`current_password`, nonempty `reason`, and exact current username in `confirmation`.
Session CSRF, input bounds and throttling apply. No self-service erasure exists.
The operation is atomic. Bad or stale confirmations leave the database untouched.

Deletion removes credentials/profile/settings/Elo/title, all stored sessions,
personal notices/reports/appeals/sanctions, queue/connection records, guesses and
exclusively owned singleplayer matches. Shared matches, other players' scores and
outcomes remain; the participant becomes an explicitly deleted anonymous identity.
Party membership names and associated messages are anonymized. Deleted ranked
players render as unlinked **Deleted player**, with no personal Elo snapshots.
Other subjects' reports and former staff actions survive with nullable actors.

Approved images retain status, answers, category, retirement state, stored bytes,
licensing, attribution, source URL and integrity/provenance fields. Submitter links,
private filenames and submitter notes are removed. Shared file references are
checked before cleanup. Pending/rejected image rows and private files are removed;
historical round image links become nullable and their answer/outcome snapshots
remain. An unapproved image referenced by an active game temporarily prevents
erasure; retry after that game completes.

A minimal permanent deletion audit retains the acting administrator, timestamp,
required reason with known target identifiers redacted, fresh random deletion
reference and outcome counts. The old account UUID is not used as its reference.
Approved-image review audits also redact known submitter identifiers. Existing
staff records retain necessary facts about other subjects.

Private file deletion occurs only after commit. Durable PendingFileDeletion jobs
survive storage failures or a process interruption. Retry from the repository root:

```powershell
.\.venv\Scripts\python.exe backend/manage.py cleanup_deleted_files --limit 100
```

A shared file is retained. Failed jobs keep a generic error without credentials or
raw storage diagnostics. Operators should run this command periodically and inspect
pending jobs. Cleanup currently uses the configured default private storage.
Infrastructure backups, historical external CSV manifests, operational logs and
third-party storage snapshots follow their separate retention policies; this tool
does not immediately erase them. Avoid entering unnecessary personal data in reasons.

## Password reset: trusted server CLI only

```powershell
.\.venv\Scripts\python.exe backend/manage.py reset_player_password --username exampleplayer
```

Two hidden prompts require matching passwords and configured Django validators.
A terminal without secure hidden input is refused. Passwords are hashed through
Django and never accepted as arguments or displayed. All stored sessions are
invalidated. Django Admin password resets and direct user deletion are disabled;
legitimate player-initiated password changes remain available.

## Schema and verification

Apply the four additive/relationship migrations after backing up the database:

- accounts.0004_account_lifecycle: nullable title verifier.
- library.0006_account_lifecycle: nullable image/import actors, explicit deleted
  reviewer marker preserving review constraints, durable file cleanup jobs.
- games.0008_account_lifecycle: nullable historical images, explicit anonymous
  participant/member identities with mutually exclusive identity constraints.
- moderation.0005_account_lifecycle: closure origin, Other, nullable historical
  actors and explicit deleted revoker marker preserving revocation constraints.

```powershell
.\.venv\Scripts\python.exe backend/manage.py migrate
.\.venv\Scripts\python.exe backend/manage.py check
```

Restart Django and clock workers after migration. No account deletion, image
removal, administrator promotion or password change occurs during migrations.
Regression tests use isolated SQLite databases and temporary media. Manually review
the closure steps and deletion dialog on desktop/mobile with synthetic accounts;
never test erasure against real player accounts or media.
