# Image contributions

`/contributions` replaces `/submit`, which redirects with history replacement.
The public library, homepage, singleplayer contribution prompt and Account Settings
link to the dashboard. New submissions and read-only details open in accessible
modals, never separate player detail routes. Escape, X and Cancel support discarding
unsubmitted drafts only after explicit confirmation when data has been entered.
Local object-URL previews are revoked when changed or closed.

## Private player workflow

Authenticated players see paginated history (24 per page), All/Pending/Approved/
Rejected/Removed filters and global Total/Pending/Approved counts. Pagination includes
Removed receipts; it is not a 24-record history cap. Probation and suspension disable
new contributions while allowing private history. Closed/inactive accounts retain
the existing normal-access restriction. Players cannot edit, withdraw or delete
submitted contributions.

New contributions require a still JPEG/PNG/WebP upload, answer, category, optional
comma-separated synonyms, source/rights category, license and attribution. Licensed
third-party sources require an HTTPS provenance URL without embedded credentials.
Owned and AI-generated images still require appropriate usage permission and credit.
The explicit permission acknowledgment records its timestamp; it does not assume
an ownership transfer or unlimited usage rights. This records the submitter's
assertion, not an automated copyright determination.

The shared upload processor keeps the existing 8 MiB, 64–4096 pixel and 12 megapixel
limits, converts to metadata-free WebP and stores under an opaque private filename.
The server never fetches a submitted reference URL. New records are pending and
unplayable until review. Creation uses the existing 20/day submission throttle,
CSRF/session authentication and fresh account restriction checks. Storage objects
left by failed database writes are queued for safe retryable cleanup.

The existing `/api/library/submissions/` write endpoint delegates to the same
upload-only rights validation and creation service. Its historical read behavior
remains compatible. Existing external-reference records remain valid and readable;
trusted administrator/import serializers continue supporting existing references.
There is no player-facing external URL upload mode. Historical external references
have no hosted preview and cannot become playable without a valid hosted image,
consistent with existing game eligibility.

## Review: one submission, one review, one image record

Administration → Image Library has Image Library and Player Submissions tabs.
The latter is the same image table filtered by a server-controlled player-origin
marker, not a second image library. It defaults to Pending, prioritizes pending
records in All, supports search by answer/player/UUID and paginates normally.
Actual submitter relationships supply identity; anonymized origins remain marked.
Administrator imports remain in the general library and imports workflow.

The general Image Library includes administrator-managed images in every review
state and player contributions only while their stored review status is Approved
(including retired Approved images for restoration/deletion). Pending and Rejected
player contributions stay exclusively in Player Submissions. The server applies
this origin/status scope before search, filtering, counts and pagination; library
detail editing and bulk review enforce the same scope. Approved contributions
appear in both views using the same image UUID. Overview separates pending player
reviews from pending import/library reviews and links to the appropriate queue.

Before approval, administrators can correct answer, synonyms, category, source,
provenance, license and attribution. Category selection remains controlled while
options load, preserving the actual stored category. Approve validates metadata
and stored image bytes, applies corrections and approves the original row in one
transaction. There is no separate label queue, second image or second approval.
Existing import label-verification requirements remain unchanged for imports.

Reject preserves the private image/metadata, records reviewer/time and excludes
the image from gameplay. The optional explanation is staff-only unless explicitly
marked Visible to player. A separate allowlisted field supplies public feedback;
internal review notes and import metadata never enter private player serializers.
General library review actions clear prior explicitly public feedback unless a new
player-review decision supplies it. Administrative mutations remain audited.

Remove requires a separate explicit confirmation and no written reason. Pending
contributions may be removed directly in this inbox. Later rejected or retired
contributions use the existing deletion service. Rejected contributions have a
delete control in their Player Submissions details; retired Approved contributions
use the Image Library deletion tool. Active approved images
must still be retired first. Removal during a live reveal is deferred until the
round ends. Django Admin generic deletion is disabled so it cannot bypass retention
receipts, audit or durable storage cleanup; its existing editing/review tools remain.

## Removal retention and account erasure

A RemovedContribution receipt stores only opaque original image UUID, original
submission timestamp and nullable submitter ownership for authorization. Removed is
a constant presentation state. It stores no image, answer, filename, synonyms,
category, source, review text or private storage path. The original ImageSubmission
row and dependent import items are deleted. Import batches and unrelated images
remain. Approved images that remain after account erasure retain required licensing
and attribution, with their origin marker and anonymous submitter.

Games, rounds, guesses and participants are never cascade-deleted by image removal.
For removed player content, round answers become a neutral Removed image label,
synonyms/metadata snapshots are cleared, guess text is redacted, and old image audit
payloads are scrubbed. Guess rows, correctness, score totals, winners and historical
outcomes remain. Deleted image bytes and old preview URLs are unavailable. Non-player
library deletion preserves its existing minimal credit snapshots and policy.

Files are deleted after commit using the existing PendingFileDeletion jobs. Shared
references are rechecked before deletion; shared files stay intact. Storage failures
and process interruptions remain retryable with `cleanup_deleted_files --limit 100`.
Private previews are no-store, owner/administrator authorized and never enter public
catalog serializers. Receipt reads require the owning session; only administrators
can review/remove. No new IP tracking or public raw media serving is introduced.

Permanent account erasure cascades to that player's receipts and clears public
review feedback from preserved approved images. Old backups and operational logs
have separate retention policies; this workflow does not claim immediate backup
erasure or recover receipts for images deleted before receipt tracking existed.

## API

- `/api/library/contributions/`: authenticated GET history/stats, upload POST.
- `/api/library/contributions/<uuid>/`: owning player GET, read-only.
- `/api/library/contributions/<uuid>/preview/`: owner or active administrator GET.
- `/api/moderation/workspace/administration/player-submissions/`: admin GET inbox.
- `/api/moderation/workspace/administration/player-submissions/<uuid>/review/`:
  admin POST approve/reject/remove, optional corrections/explanation/visibility;
  remove requires `confirm=true`. Repeating a confirmed removal is idempotent.

## Migration and verification

`library.0007_contributions` adds player_contribution, rights_acknowledged_at and
player_review_explanation to ImageSubmission, plus the content-free receipt model.
It identifies existing regular-player submissions using their submitter relationship
while excluding known import links/digests and staff-owned legacy records. Original
fields, approved statuses and files are preserved. Ambiguous historical staff uploads
and already-anonymized records remain legacy rather than inventing their origin.
All new player contributions, including those submitted by administrators through
the player dashboard, receive the explicit marker at creation.

Apply migrations with the repository .venv interpreter after database backup and
restart Django/clock workers. Tests use isolated SQLite and temporary media for every
backend test. Browser verification uses separate accounts, database and generated/
included development fixtures. No real player accounts or library images are deleted
while testing. Frontend verification may use `npm test -- --maxWorkers=4` to avoid
CPU contention on this Windows computer. Production storage was not directly tested;
shared storage abstractions and simulated cleanup failures are covered.
