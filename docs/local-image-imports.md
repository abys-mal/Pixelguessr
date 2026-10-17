# Local Pexels photograph imports

The importer uses `ImageSubmission`, its normal validation, the configured private
`image_file` storage, and the existing staff-review operation. It never approves
automatically, modifies source JPGs, downloads anything, or changes the admin UI.
The additive `library.0004_local_import_provenance` migration adds a unique private
content digest and private import metadata; existing submissions remain unchanged.

## Prototype metadata policy

This local prototype enables `PEXELS_PROTOTYPE_METADATA=True` in `.env`.
It requires `DEBUG=True`; the setting defaults to false and cannot be enabled in
production. Imported photographs use `attribution="Pexels"` and
`license="Pexels License"`. The photographer and original Pexels photo-page URL
are optional. An unavailable URL stays blank, and missing individual source
details or `metadata_verified=no` do not prevent import or approval in this mode.
This is an explicit prototype policy, not a claim that individual provenance was
verified. Optional photographer/source fields remain in the CSV and private
metadata for later enrichment; supplied URLs still undergo validation.

Label review, file validation, storage verification, duplicate detection, staff
permissions and explicit approval remain required. The current canal photo stays
pending at the user's request. Turn the setting off to restore the individual
photographer/URL/metadata verification requirements described below. Reviewed
records remain protected from importer overwrites.

## Import and review

From PowerShell in `C:\Users\actian\source\Pixelguessr`:

```powershell
.\.venv\Scripts\python.exe backend/manage.py migrate
.\.venv\Scripts\python.exe backend/manage.py import_local_images "C:\Users\actian\Downloads\pexel-pictures"
```

The default manifest is
`C:\Users\actian\source\Pixelguessr\backend\private-media\imports\pexels-images.csv`.
Use `--manifest "C:\path\collection.csv"` for another collection. Filenames are
relative to the selected source directory; JPG/JPEG suffixes are case insensitive
and subfolders are included. The initial run creates blank label rows for new
photographs and marks them `needs_label`, rather than inventing answers. Fill those
rows and rerun. The current collection has eight approved prototype photographs;
its tropical waterway has a provisional **canal** answer
and still needs manual label review.

Open the CSV in a UTF-8 capable editor or Excel. Preserve all columns and save as
UTF-8 CSV. Close the editor before running commands; Windows may prevent atomic
replacement of an open CSV. In `accepted_synonyms`, enter a JSON array such as
`["streetcar", "trolley", "tramcar"]`. Category values are existing slugs:
`nature`, `animals`, `food-drink`, `objects`, `places`, `art-culture`.
Difficulty is `easy`, `medium` or `hard`; descriptions and difficulty remain private
curation metadata and do not change gameplay or scoring.

Review each photograph, its short canonical answer, synonyms and category. Avoid
ambiguous scenes or replace the label before setting `label_verified` to `yes`.
Outside prototype mode, find and verify the actual photographer, HTTPS Pexels `/photo/` page and applicable
license; enter those in `photographer`, `pexels_source_url` and `license` before
setting `metadata_verified` to `yes`. Update review notes to describe any remaining
issues. The importer does not infer names or URLs from filenames. Unknown metadata
stays blank in the CSV and is explicitly `UNVERIFIED` in required database fields.

Apply edited metadata without needing the Downloads folder:

```powershell
.\.venv\Scripts\python.exe backend/manage.py import_local_images --update-metadata --manifest "backend/private-media/imports/pexels-images.csv"
```

Only pending submissions can be corrected. Reviewed submissions and their stored
files are never overwritten. Keep the generated identity and checksum columns
unchanged. A duplicate filename with changed JPEG bytes is an error; review the
new input using a separate manifest instead of attaching old labels to new content.
Exact duplicates share one library record. If duplicate rows disagree, reconcile
their metadata before collection approval; the first stored filename is retained
as provenance.

Once every selected row is imported, its metadata satisfies the active policy, and all labels are suitable,
explicitly approve the collection with an **existing active staff username**:

```powershell
.\.venv\Scripts\python.exe backend/manage.py review_local_images "backend/private-media/imports/pexels-images.csv" --reviewer YOUR_STAFF_USERNAME
```

The importer account is inactive, unprivileged and has no usable password; it cannot
approve anything. Native moderation access alone does not grant image-review
permissions. The review command validates the entire collection before invoking
`review_images`; it records the normal reviewer and timestamp. Verified metadata
is required outside prototype mode; verified labels are always required by model validation, including when the existing
shared review workflow is used. Rejected images require separate review, and
already approved rows are left alone. Rerunning approval is safe.
For a partially reviewed collection, save a separate CSV containing only the
reviewed rows and approve that CSV. Leave unreviewed rows in the main manifest;
their database status remains pending. Keep the same columns and checksum values.

## Storage, conversion and recovery

The local configuration stores opaque UUID-named WebPs under
`backend/private-media/images/`. Both media and manifests are Git-ignored; they must
be backed up independently. Storage operations use the configured Django storage
backend and do not require filesystem `.path`, public media routes or cloud setup.

Inputs must be still JPEGs of at most 8 MiB. Pillow applies EXIF orientation, converts
to RGB, downsizes only when needed to meet 64–4096-pixel and 12-megapixel limits,
preserves aspect ratio, strips metadata and encodes WebP at quality 90. Converted
output must also fit the 8 MiB limit and is reopened and decoded before registration.
Normal HTTP upload limits remain strict; automatic downsizing is local-import only.

Three checksums serve different purposes: `sha256` identifies original JPEG bytes;
`content_sha256` hashes oriented/resized RGB dimensions and pixels to detect copied
or metadata-only duplicate images; `stored_sha256` checks the permanent WebP.
Database uniqueness protects the content digest. Original filenames are private
provenance, never storage keys. All game references continue to use normal library
IDs and stored image names.

Each photograph has its own database transaction. New private files are cleaned up
when registration or storage verification fails, including a storage backend that
writes before raising. Cleanup failures explicitly report the private storage key
for operator recovery; no broken library record is intentionally retained. The
manifest is atomically replaced after each image. If a crash or file lock prevents
an update after a commit, rerun the importer: durable content digests recover the
existing record without creating another image. Database/storage errors produce
nonzero exit status and per-image errors; successful pending imports remain.
If approval commits but updating the CSV fails, the error explicitly reports that
state; close the editor and rerun approval to reconcile the manifest.

## Verify and retire the Downloads copy

```powershell
.\.venv\Scripts\python.exe backend/manage.py import_local_images --verify-only --manifest "backend/private-media/imports/pexels-images.csv"
```

This command does not read the original JPGs. It requires every row to be imported
without unresolved import errors, checks database/storage references and WebP
checksums, fully decodes each file, and reports unique-image count and WebP bytes.
The source import reports conversion, duplicate, failure and labeling counts.
Do not delete unimported or failed sources.

After verification, review the contact sheet/photographs and metadata, and back up
**the SQLite database, private media, and CSV together**. Keep original JPEGs in a
separate backup if you want original resolution or future re-encoding: imported
WebPs are lossy and some photographs were downscaled. Only after successful
verification and checking the backups should you manually delete the original
Downloads folder. Neither management command deletes it. The folder can be absent
during later metadata corrections, approval and gameplay.

Pending images are deliberately ineligible for gameplay. After explicit approval,
singleplayer, parties and ranked duels all use the same `approved_images()` selector
and `image_fields()` snapshots. The existing compositor reads only private WebPs.
To play-check, launch Django/Vite and both normal game clocks, start a singleplayer
game and two-account party/duel, and confirm reveal frames work. Selection is random,
so a particular newly approved photograph is not guaranteed in the first game.
Focused tests cover this shared eligibility and compositor with synthetic approved
imports; real photographs remain pending until their provenance is verified.
