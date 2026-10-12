# Phase 2.1 verification · 2026-10-11

Implemented directly in `C:/Users/actian/python code/Pixelguessr` using the existing Django/SQLite and React/Vite project. No clone, commit, push, pull request, Docker, Redis/PostgreSQL service or cloud dependency was used.

| Check                              | Result                                                                                                |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Standard backend pytest            | 81 passed; 6 concurrency cases intentionally skipped for shared in-memory SQLite                      |
| File-backed SQLite concurrency     | All 6 skipped cases passed separately against a disposable test database                              |
| Frontend Vitest                    | 25 passed across 3 files                                                                              |
| Ruff lint / format                 | Passed                                                                                                |
| ESLint / Prettier                  | Passed                                                                                                |
| TypeScript / Vite production build | Passed                                                                                                |
| Django checks                      | Passed, no issues                                                                                     |
| Migration drift                    | No changes detected                                                                                   |
| Local migrations                   | `games.0003` and `games.0004` applied                                                                 |
| Data preservation                  | Original row/column fingerprints unchanged across 20 tables immediately after migration               |
| Approved hosted library            | Existing 4 approved images preserved; no seeding or moderation changes                                |
| Browser HTTP readiness / frontend  | Both 200                                                                                              |
| Browser full game                  | Exactly five sequential rounds; explicit Next Round; final total, each outcome/score and solved count |
| Browser forfeits                   | Round 1 and Round 5 forfeited after full reveal for 0; Round 5 opened Final Results                   |
| Browser normalized synonym         | `BIKE!!` accepted as bicycle, earning 245 points at server acceptance                                 |
| Browser post-reveal guesses        | Cherries/lighthouse recorded solved with 0 points, distinct from forfeits                             |
| Browser refresh/reconnect          | Round results, current round and 245-point total survived refresh and Django interruption/restart     |
| Browser Play Again                 | Fresh game, Round 1, 0 total; previous completed game retained                                        |
| Responsive browser                 | Desktop, 390px, 320px; gameplay and final results fit without horizontal overflow                     |
| User refinement                    | Live potential-score counter removed; only cumulative and earned round scores displayed               |

Backend tests verify five planned rounds/one active round, 45-second timing, canonical/synonym matching, incorrect guesses without penalties/cooldowns, exact half-up scores (1000/810/563/250/63/0), post-reveal solved/0, guarded forfeits, duplicate scoring prevention, protected pending images, skip/start-over rejection, private answers and source paths, guests/accounts, refresh/cache loss, expiry preserving earned points, stale retries preserving active-game recovery, library sizes 1/2/4/5/6, empty/pending/external-only libraries, missing files, approval changes, and ignored client score/timing claims. Pixel tests retain mask checks on tile edges and interiors at 0, 22.5, 44.999, 45 and 50 seconds.

Migration tests create legacy one-round data on the old schema in an isolated database and upgrade again, checking stored scores, answers, synonyms, owners, images, timestamps, 30-second historical durations and completed outcomes. The development database was backed up before migration; account/library/moderation and all original game columns were verified unchanged before browser test records were added.

Concurrency tests use real SQLite file writer locks: duplicate correct guesses, correct/forfeit races, repeated Next Round, repeated starts, and simultaneous new starts with identical or different request UUIDs. They use serialized test rollback to retain migration-seeded categories. `TEST_SQLITE_FILE` affects only test settings; default tests remain isolated in-memory SQLite. No automated test uses development data.

Frontend tests cover cumulative scores, round counter/progress, keyboard guesses, round results and focus, five-round progression, final table and Play Again, forfeit visibility/outcomes, zero-point solves, refresh/reconnect, empty/expired games, delayed poll rejection and timer-only forfeit denial. There is a regression assertion that Current Score is absent. Reveal-component tests retain authorized masked-frame fetching, confirmed tile transitions, retries, and blob cleanup.

No known gameplay failures remain. The small original fixture library necessarily repeats one image in a five-round game; immediate repeats are avoided. Masked frame delivery remains about once per second and needs production/multiplayer load optimization. PostgreSQL/Redis/S3 integration and deployment were not exercised. Legacy one-round games remain read-only history; record retention cleanup remains future work. Temporary owned verification servers are stopped after completion. See README for local startup/testing commands.
