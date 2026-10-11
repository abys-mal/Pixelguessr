# Original development image library

The four development illustrations are original procedural artwork authored for Pixelguessr in `backend/library/dev_art.py`. The artwork is dedicated to the public domain under CC0 1.0; no third-party image, network download, font, or image-search service is used. The original source makes each illustration reproducible. Attribution is stored for transparency, although CC0 does not require it.

| Canonical answer | Accepted synonyms        | Category     |
| ---------------- | ------------------------ | ------------ |
| lighthouse       | light house, beacon      | Places       |
| bicycle          | bike, cycle              | Objects      |
| cherries         | cherry                   | Food & drink |
| hot air balloon  | balloon, hot-air balloon | Objects      |

Attribution: **Original Pixelguessr development artwork, created for this project (CC0 1.0).**

From `backend/`, run `..\.venv\Scripts\python.exe manage.py seed_dev_images` to import **pending** images through the ordinary SubmissionSerializer pipeline (upload validation, metadata stripping, normalized WebP, opaque private filenames). Review these in Admin, or run `..\.venv\Scripts\python.exe manage.py seed_dev_images --approve` to explicitly review just these known originals through the same staff review service used by Admin. Existing user submissions are never approved by this command. Edited development records cause an error rather than being overwritten; previously rejected fixtures stay rejected.

The command is development-only and requires DEBUG=True and SQLite. Deterministic record UUIDs make repeated imports safe. A disabled staff provenance actor `pixelguessr-dev-curator` records the upload/review audit trail. It has an unusable password and cannot sign in; it is **not an admin login account**. Create your own administrator using `manage.py createsuperuser`. No default administrator password is installed.

Only approved hosted images are eligible for gameplay. External reference records remain private metadata and are never fetched during play. These four illustrations exercise the game; a production library needs a larger staff-reviewed collection and retained source/license evidence.
