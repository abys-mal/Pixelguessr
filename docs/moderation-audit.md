# Pixelguessr moderation/admin browser checklist

This is the historical Phase 5.2 checklist. Native moderation now replaces the
moderator Admin workflow: only active superusers may enter Django Admin. Use
[native moderation](native-moderation.md) for current roles, appeal rules, setup
and manual verification. Existing historical audit results remain relevant.

This checklist uses the existing project, Django Admin, session authentication, and model permissions. It creates a disposable database and image directory; it does not clone the project or modify the development database. Use only the `audit_` accounts below for sanctions and role changes.

## Start an isolated local instance

In PowerShell, prepare a consistent SQLite copy and isolated settings:

```powershell
cd 'C:\Users\actian\python code\Pixelguessr'
$auditRoot = Join-Path $env:TEMP ('pixelguessr-moderation-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $auditRoot | Out-Null
$env:PIXELGUESSR_AUDIT_ROOT = $auditRoot
@'
import os, secrets, shutil, sqlite3
from pathlib import Path
repo = Path.cwd()
audit = Path(os.environ['PIXELGUESSR_AUDIT_ROOT'])
source = sqlite3.connect(repo / 'backend' / 'db.sqlite3')
target = sqlite3.connect(audit / 'db.sqlite3')
source.backup(target)
source.close()
target.close()
shutil.copytree(repo / 'backend' / 'private-media', audit / 'private-media')
lines = [
    'from config.settings import *',
    "DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': " + repr(str(audit / 'db.sqlite3')) + ", 'OPTIONS': {'timeout': 20}}}",
    'MEDIA_ROOT = ' + repr(str(audit / 'private-media')),
    'SECRET_KEY = ' + repr(secrets.token_urlsafe(48)),
    "SESSION_COOKIE_NAME = 'pixelguessr_audit_session'",
    "CSRF_COOKIE_NAME = 'pixelguessr_audit_csrf'",
    "CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:5174', 'http://127.0.0.1:8012']",
]
(audit / 'pixelguessr_audit_settings.py').write_text('\n'.join(lines), encoding='utf-8')
print('Audit folder:', audit)
'@ | & .\.venv\Scripts\python.exe -X utf8 -
$env:PYTHONPATH = $auditRoot
& .\.venv\Scripts\python.exe backend/manage.py migrate --settings=pixelguessr_audit_settings
& .\.venv\Scripts\python.exe backend/manage.py createsuperuser --settings=pixelguessr_audit_settings
```

Choose `audit_admin`, a test email, and a unique test password at the prompts. The different secret and cookie names isolate the audit session from your normal development session. Keep the printed audit folder private: the copy contains existing data. Do not interact with copied real accounts.

Start Django in that terminal:

```powershell
& .\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8012 --settings=pixelguessr_audit_settings
```

In another terminal:

```powershell
cd 'C:\Users\actian\python code\Pixelguessr\frontend'
$env:API_PROXY_TARGET = 'http://127.0.0.1:8012'
npm run dev -- --host 127.0.0.1 --port 5174
```

Use `http://127.0.0.1:5174` for the game and `http://127.0.0.1:8012/admin/` for Django Admin. Keep these ports free; do not stop an unrelated service. For active-game deadline tests, run the existing `party_clock` and `ranked_clock` commands in additional terminals with the same `PYTHONPATH` and `--settings=pixelguessr_audit_settings` argument.

## Create the three roles safely

1. Sign into Django Admin as `audit_admin`.
2. Under Users → Add, create `audit_player` and `audit_moderator`, each with a test email and password. Both begin as regular users.
3. Under Groups → Add, create **Audit moderators** with exactly these model permissions:
   - Moderation / Report: view and change.
   - Moderation / Sanction: view, add, and change.
   - Accounts / User: view, for account lookup.
   - Optional image-review testing: Library / Image submission: view and change.
4. Edit `audit_moderator`: enable **Staff status**, keep **Superuser status** unchecked, and assign **Audit moderators**. Do not grant group management, user-permission assignment, or deletion permissions.
5. Verify `audit_player` has neither staff nor superuser status and no privileged groups. `audit_admin` is the administrator.

Staff status permits admin sign-in; individual model permissions control tools. Superusers administer roles/groups and can reverse closure. Pro/Master/Legend titles are cosmetic; they grant no authority. The disabled development curator is not an admin login account.

To remove a moderator, use the administrator to clear staff status, privileged groups, and direct permissions. Expect admin access to end on the next request while historical sanction/title actor records remain valid. Never grant a moderator superuser status merely to make a tool appear.

## Browser checks and expected results

### Profile and logout

- Sign into the game as `audit_player`. Open Profile. **Expected:** Sign Out sits beside `@audit_player`; Account settings remains accessible.
- Open Account settings. **Expected:** no redundant Sign Out button.
- Open someone else's public profile. **Expected:** no Sign Out control in that profile header.
- Use Tab/Shift+Tab and Enter on Sign Out. **Expected:** visible keyboard focus, one request, guest navigation/profile prompt after completion, and continued guest singleplayer availability.
- Try a narrow mobile viewport and a long valid username on a disposable account. **Expected:** no page-wide horizontal overflow; history columns remain available by scrolling the table.
- Review a ranked history with victory, forfeit, and No Contest results. **Expected:** WIN green, LOSS red, NO CONTEST neutral; Forfeit remains explicit. Scores, Elo deltas, dates, opponents, and pagination remain intact. Ranked currently has no match-level draw; washed rounds are not draws or No Contests.

### Reporting

There is currently no player-report form in React. Test the existing report API from the browser console while signed into the **audit** game origin. Obtain the moderator's UUID from the public profile JSON at `/api/auth/profiles/audit_moderator/`, then replace `SUBJECT_UUID` below:

```javascript
const csrf = await (await fetch('/api/auth/csrf/')).json();
const response = await fetch('/api/moderation/reports/', {
  method: 'POST',
  credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf.csrfToken },
  body: JSON.stringify({
    subject: 'SUBJECT_UUID',
    category: 'fair_play',
    details: 'Synthetic audit report; no real misconduct alleged.',
  }),
});
console.log(response.status, await response.json());
```

- **Expected:** 201; the reporter is the current player. Self-reporting, invalid IDs/categories, blank details, and details over 2000 characters return 400. Missing authentication or CSRF returns 403.
- Repeat a valid report. **Expected:** another separate report; the existing policy permits duplicates. The eleventh attempt in a day returns 429. Invalid attempts also count toward the existing throttle.
- Sign into Admin as `audit_moderator`; open Reports and the test report. **Expected:** reporter, subject, category, details, and creation time are read-only. There is no broken Add Report form.
- Set **Resolved at** using the date/time controls and save. **Expected:** resolution persists and History records the acting moderator/time. Resolution does not automatically issue a sanction.
- Sign in as `audit_player` and visit Admin. **Expected:** denied. Report listing/update/deletion is not exposed through the player API.

### Warnings

- As moderator, add a sanction for `audit_player`: Fair Play, Warning, a clearly marked synthetic reason, and current start time. Leave expiry blank. **Expected:** issuer is assigned server-side and expiry is exactly start + 90 days.
- Refresh the player's game page. **Expected:** a notice banner; Account settings shows the reason and Acknowledge warning.
- Before acknowledgment, try Ranked, party membership, image submission, and another report. **Expected:** restricted. Singleplayer remains available under the existing policy.
- Acknowledge the warning. **Expected:** the restriction banner disappears after authentication refresh; the notice remains marked Acknowledged until expiry/revocation. Repeated acknowledgment retains its first timestamp. Another player cannot acknowledge it.
- For an expiry check, create a separate warning beginning 91 days ago. **Expected:** stored for history, absent from active notices and restrictions.

### Probation, suspension, and closure

- Revoke prior active test sanctions before testing each kind independently.
- Add probation starting now, with an expiry a few minutes later. **Expected:** Ranked entry and image submissions denied; singleplayer, parties, and reporting remain available. Expiry or authorized revocation restores access.
- Add suspension starting now with a short expiry. **Expected:** login denied, existing account sessions/private game requests blocked, and active sockets lose access on their next check. Reinstatement follows expiry/revocation. Sign Out must still flush a stale or blocked session.
- During a ranked match, impose a restriction on the test player. **Expected:** further guesses/images denied; existing disconnect/grace rules settle the match. No instant Elo penalty or changed match rule is introduced.
- During a two-player party, warn/suspend its test host. **Expected:** host requests fail; the existing host presence/grace timeout ends the party. Stored scores are not rewritten.
- Add Closed to the test player with no expiry. **Expected:** login remains blocked; setting `is_active=True` alone does not reopen it. Moderator Revoke is denied, including mixed selections containing closure. Administrator Revoke restores access while preserving the sanction record.
- Public profiles/history and active-user leaderboard visibility follow the existing policy: a sanction does not automatically set `is_active=False` or hide those public records. Guest access is not a device ban.

### Admin permissions and audit integrity

- Temporarily remove change-sanction permission from the moderator group while retaining view. **Expected:** the sanction list is readable, but Revoke is unavailable and crafted mutation requests are rejected. Restore the permission afterward.
- With optional image permissions, submit a test image with no synonyms and review it. **Expected:** pending until explicit approval/rejection; both decisions work with `[]` and record reviewer/time plus Admin History. View-only staff cannot approve/reject.
- Inspect a sanction's read-only detail and History. **Expected:** original issuer/start/reason remain unchanged; revocation records actor, target account ID, timestamp, and an Admin History entry. A repeated Revoke does not replace the first actor/time.
- Ordinary users cannot issue/revoke sanctions, edit roles, or alter audit records. Non-superusers cannot edit staff/admin accounts, reset their passwords, promote a regular user through hidden fields, or expand group permissions.
- In a disposable cosmetic-title test, revoke a Pro/Master/Legend title using another moderator. **Expected:** original verifier/time are preserved; assigning a different title or owner records fresh verification metadata. The label does not change Elo or permissions.

Stop only your audit servers when finished. Keep the normal development terminals separate. The audit settings are explicit per command; do not apply test roles/sanctions to the main database.
