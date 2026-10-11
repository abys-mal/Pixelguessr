# Phase 2 verification · 2026-10-11

Implemented and verified directly in `C:/Users/actian/python code/Pixelguessr`, preserving the existing Django/library/accounts/games structure and React/Vite frontend. Python 3.13.2, Node 24.21.0. No Docker, clone, commit, push, or pull request was used for Phase 2.

| Check                              | Result                                                                                                                            |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Django system checks               | Passed, no issues                                                                                                                 |
| Local SQLite migrations            | Additive `games.0002` applied successfully                                                                                        |
| Migration drift                    | No changes detected                                                                                                               |
| Backend pytest                     | 48 passed, isolated SQLite/in-memory services                                                                                     |
| Ruff lint / formatting             | Passed                                                                                                                            |
| Frontend Vitest                    | 21 passed across 3 files                                                                                                          |
| ESLint / Prettier                  | Passed                                                                                                                            |
| TypeScript / Vite production build | Passed                                                                                                                            |
| HTTP readiness and frontend        | Both returned 200                                                                                                                 |
| Browser empty library              | Clear empty-library message before explicit fixture review                                                                        |
| Browser guest gameplay             | Real start, incorrect Enter submission, zero-penalty retry, countdown, randomized reveal                                          |
| Browser full reveal                | At 0s / 400 tiles the round remains active and accepts guesses                                                                    |
| Browser synonym                    | `BalloOn!!` solves `hot air balloon`; answer/credit disclosed only on success                                                     |
| Browser refresh                    | Existing round and completed success recover without a new round                                                                  |
| Browser server interruption        | Last image retained with reconnect message; restarting Django automatically resumes the same guest round and authoritative reveal |
| Browser Play Again / homepage      | New round starts; homepage Singleplayer card links to real game                                                                   |
| Browser responsive layout          | Desktop, 390px and 320px; no horizontal overflow                                                                                  |

Backend coverage includes guest CSRF/ownership, cross-session denial, account participation, pending/external/empty library rejection, validation, canonical/synonym normalization, no cooldown/penalty, idempotent starts/guesses, completion, expiry, abandoned rounds, configuration/answer snapshots, missing storage, and approval changes during creation. Decoded-image tests examine tile interiors **and boundaries** at 0, 15, 29.999, 30, and 35 seconds; unrevealed pixels stay opaque even with forged full-reveal query parameters. Cache loss preserves reveal order/state. Four original CC0 development fixtures are tested as pending by default and explicitly reviewed; unrelated pending user submissions stay pending. The fixture-command test skips on PostgreSQL because that command deliberately requires development SQLite.

Frontend coverage includes real page controls and keyboard form submission, saved/fully revealed/completed rounds, empty/expired/error states, connection recovery, stale poll rejection, legacy route redirect, masked-frame fetching, only-confirmed tile transitions, picture retries, and blob-resource cleanup, alongside the existing auth/routing regressions.

Local SQLite now includes four explicitly reviewed original illustrations; development database/private-media remain ignored local data. No default administrator was created. The disabled `pixelguessr-dev-curator` has an unusable password and is solely an audit actor, not an admin login. Use `manage.py createsuperuser` for your own administrator.

Phase 2 did not exercise PostgreSQL, Redis, Docker, S3, production deployment, or multiplayer. Those configurations are preserved. Masked frame generation is CPU-bound and currently polled about once per second; shared transport/compositor performance and abuse controls need separate multiplayer/production validation. Guest recovery requires the original session cookies; round expiry defaults to 24 hours. Old rounds are retained; automatic retention cleanup is a future task.

Temporary development servers used for verification are stopped after review. Startup and fixture-review commands are documented in README.
