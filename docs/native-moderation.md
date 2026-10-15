# Native moderation workspace

The native workspace lives at `/moderation`, separate from the game layout. Home
shows actual pending reports/appeals and an empty staff announcements area reserved
for future publishing. Players supports username search, account context, sanctions,
reports, appeals and a chronological audit timeline. Reports and Appeals are paginated
inboxes with pending/all-history filters. Internal notes are staff-only.

## Install and access

From `C:\Users\actian\source\Pixelguessr\backend`:

```powershell
..\.venv\Scripts\python.exe manage.py migrate
# If no administrator exists, create one interactively:
..\.venv\Scripts\python.exe manage.py createsuperuser
# Grant an EXISTING regular account native moderator access:
..\.venv\Scripts\python.exe manage.py moderator_access PLAYER_USERNAME --actor ADMIN_USERNAME
# To remove it:
..\.venv\Scripts\python.exe manage.py moderator_access PLAYER_USERNAME --actor ADMIN_USERNAME --revoke
```

Migrations `moderation.0002` and `0003` add appeals, audit activity, internal notes,
replacement links and report resolution metadata, then import existing sanction
issuance/reversal history into the activity timeline. They do not change existing
sanction effects, accounts, scores, images or original sanction records. Existing
overlapping historical sanctions are retained; reverse unwanted duplicates before
issuing/replacing a sanction of that type.

Administrators are active superusers. Moderators hold
`moderation.access_workspace`, directly or through a group, without `is_staff`.
Grant/revoke commands require an administrator actor and record an audit entry.
Administrators can also grant/revoke access from ordinary player profiles. Revoking
access removes the direct permission and membership in groups that confer it.
Other group memberships are preserved. Legacy `is_staff` account/administrator
roles are managed in Django Admin; staff status alone does not grant native access.
Only active superusers can enter Django Admin, including its login and mutation routes.

Run the usual four development processes. Vite also proxies `/admin` and `/static`
so the administrator link works from the game origin. Production must route those
paths to Django/admin static assets as described in the README.

## Sanctions and appeals

Public reason and internal note are optional. Players see a neutral notice when
the public reason is empty. Warnings expire after 90 days; probation/suspension
may have a chosen future expiry or no expiry. Closure has no expiry. Unlimited
warnings are allowed; other kinds permit one active sanction each. Scheduled
non-warning sanctions also reserve that type to prevent future overlap.
Different kinds may coexist. No mandatory escalation exists. Probation and
suspension forms explicitly offer Indefinite or Fixed duration; switching modes
clears the prior expiration. Indefinite sends `expires_at: null`. Replacements
prepopulate the original duration and may freely change it before submission.

Reversal requires confirmation and preserves the original record. Replacement
prepopulates its current properties, atomically reverses the original and creates
a linked successor. Replacing a closure also requires an administrator because
replacement reverses the original. Moderators cannot search/review or moderate
staff, native moderators or administrators; administrators can.

Players open Account Notices at `/account-notices` using their
normal authenticated session. Suspension preserves login, settings, appeals and
singleplayer; probation also preserves parties. Warnings only create notices.
Closure blocks authenticated access and has no appeal. There is no separate
notice-login endpoint or limited authentication session. See
[current enforcement rules](moderation-enforcement.md) for the complete matrix,
active-game transitions, live updates and recovery behavior.

Warnings have one appeal per individual sanction, even after a denial. Probation
appeals have a 30-day cooldown after an upheld decision; suspension appeals have
90 days. Both are immediately appealable after issuance. The deadline uses the
latest upheld appeal’s `resolved_at` for that player and type, never the sanction
or submission time. Approved and changed appeals do not start a cooldown. Pending
appeals block duplicates without creating a cooldown date.
These cooldowns and the one-pending-appeal limit follow the player and sanction
type across replacement/reversal. A pending appeal continues to block further
appeals after the cooldown. Expired/reversed sanctions are not appealable.
Reversing or replacing a sanction marks pending appeals **Sanction changed**.
Reviewing an expired sanction's pending appeal also records Sanction changed.
Upholding never prevents an independent later reversal.

Native mutations acquire the per-player database writer lock before mutable
reads. SQLite and PostgreSQL serialize issuance, replacements, cooldown decisions,
pending limits and reviews. Conditional database uniqueness additionally protects
warning appeal and pending probation/suspension appeal limits. Audit failures roll
back the corresponding mutation. Issuance and reversal through Django Admin also
record native activity and resolve pending appeals.

## Manual verification

Use disposable accounts in an isolated database when testing sanctions. Keep
the normal development database and actual users separate.

1. Create an administrator, a regular moderator account and two regular players.
   Grant moderator access using the command above. Sign in separately in browser
   profiles. Confirm Mod Panel appears only for the moderator/administrator, the
   workspace has its own navigation and Return to Game works. Moderator `/admin/`
   requests must redirect to the restricted admin login.
2. Search a player in Players. Issue a warning with both optional fields blank,
   then another warning. Confirm both appear. Add probation; a second probation
   must be rejected. Player notices must never expose an internal note.
3. As the player, open Account Notices using its link in Account Settings. Submit an explanation for the warning.
   As moderator, uphold it in Appeals. The player cannot appeal that warning again;
   independently reversing it from Players must still work.
4. Appeal probation, then replace it in Players. Confirm the predecessor remains,
   the successor is linked, the pending appeal becomes Sanction changed, and any
   existing upheld-decision cooldown remains in effect; the changed pending appeal
   does not create one. Activity records every actor/time.
5. Suspend the player while already signed in. Normal sign-in, settings and
   singleplayer remain available. Parties, ranked and submissions are denied.
   Submit an appeal in Account Notices, reverse it from Appeals, and verify new
   multiplayer entry works without losing sanction history.
6. Close the player account. Confirm closure cannot be appealed or reversed/replaced
   by a moderator. As administrator reverse it; the original record remains.
7. Submit a report using the existing `/api/moderation/reports/` API. Review its
   context/history, issue a sanction directly from the player panel, then resolve or
   dismiss the report. The reporter remains private to authorized staff. Existing
   duplicate policy and ten-per-day throttle remain unchanged.
8. As administrator grant/remove native access from another ordinary account.
   Check the audit timeline and next-request access revocation. Verify moderators
   cannot view/sanction staff even with crafted API requests.
9. Check desktop and narrow mobile layouts, keyboard Tab/Enter/Escape, modal focus
   and restoration, cancellation, loading/error/empty states and pagination.

The announcements area intentionally has no publishing controls yet. Player report
submission still uses the existing API; this phase does not add a separate report form.
No notification/email delivery is added. The default player-detail response includes
the full history; very large histories may warrant paginating those sections later.
