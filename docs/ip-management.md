# Administrator IP Management

Open **Moderation → Administration → IP Management** at
`/moderation/administration/ip-management`. Blacklist and Whitelist are the two
tabs. Only active accounts with both `is_staff` and `is_superuser` can retrieve or
change entries. Moderator workspace permission alone grants no access.

## Rules and interface

Both lists support exact IPv4/IPv6 addresses, reason/address search, editing,
deletion confirmation, and the shared Page X of Y pagination. Reasons are required
and administrator-only. IPv6 is compressed/lowercased; IPv4-mapped IPv6 becomes
IPv4. Scoped addresses, hostnames and CIDRs are rejected for entries. Database
uniqueness is per list, including normalized equivalent addresses; adding a
duplicate returns an error without overwriting anything.

Moderators and administrators are exempt from all blacklist activities, including
sign-in from a blocked network. The exemption uses the existing active moderator/
administrator role definitions, including group-granted moderator permissions.
Roles are re-read when a restriction would apply, so stale sessions or socket
permission caches do not retain exemptions after demotion. Staff still need valid
credentials, normal authorization and CSRF protection, and remain subject to
account sanctions and infrastructure rate limits. A username supplied to a login
form never grants an exemption before its password is verified.

The six selectable activities are Account registration, Login, Singleplayer,
Parties, Image submissions, and Community interactions. Except for Login, these
rules apply only to signed-out visitors. Signed-in accounts ignore them. Ranked
Duels requires sign-in, so there is no separate ranked restriction. Existing
ranked-only records are retained, labeled as legacy entries, and have no effect;
editing an entry clears the legacy ranked flag. Select at least one current
activity when saving. Temporary entries use a custom local date/time picker with the browser
time zone shown; requests and storage use UTC. Indefinite entries have no expiry.
Every enforcement check compares expiry with current time, so expiration needs no
clock command or cleanup job. Expired entries remain available for audit/reuse.

Whitelist entries contain only an address and internal reason and are indefinite.
A matching whitelist overrides all rules in this feature, even when the same IP
exists in both lists. It never grants authentication, staff privileges, sanction
exemptions, CSRF exemptions, or rate-limit exemptions. Removing it restores any
still-active blacklist immediately.

No accounts are automatically sanctioned, no failed-login auto-banning is added,
and IPs are not treated as user identities. Shared network addresses can affect
many unrelated players. No account-to-IP history is collected by this feature.

## Enforcement policy

HTTP enforcement runs after session authentication and before protected views:

| Activity | Covered operations |
| --- | --- |
| Registration | Registration API and Django Admin account creation POST |
| Login | Denies non-staff sign-in after credential verification and deletes an accessing non-staff session |
| Singleplayer | Signed-out singleplayer start/state/guess/image routes |
| Parties | Signed-out party creation, reads/images, join, start, guesses, lobby, kick, next-round operations |
| Image submissions | Signed-out submission attempts; normal authentication requirements still apply |
| Community interactions | Signed-out ordinary report attempts; normal authentication requirements still apply |

Login restrictions invalidate the accessing session for non-staff accounts, even
when accessing session checks, account support, notices, cleanup routes or public
reads. Only that session is deleted; the same account's sessions on other networks
are not globally revoked. Session checks return the signed-out state and clear the
cookie. Replaying a deleted cookie, removing the rule, or changing networks does
not restore it: a fresh allowed sign-in is required. Guest play remains available
unless the relevant guest activity is also restricted.

Account-update sockets recheck once per second and publish a signed-out state
before closing, so idle signed-in tabs are handled too. Party and ranked sockets
recheck on their normal ticks/actions, delete an affected session and close 4403.
Unknown offline sessions cannot be located by network (no IP history is collected);
they are invalidated when they next access from that network.

Registration and login are independent. If registration is allowed but login is
blocked, an account can be created, but automatic sign-in is skipped; the response
includes `login_required: true` and the registration screen explains this.
Existing authorization and sanctions still apply to every support operation.

Guest activity restrictions still permit safe cleanup POSTs. Login restrictions
invalidate an authenticated session even on cleanup endpoints. Existing disconnect
leases and game clocks handle those departures; scoring and deadlines are unchanged.
Normal authorization, account sanctions and CSRF checks remain authoritative.

Party and ranked queue/match WebSockets check rules before connecting, before
actions, and before state pushes/ticks. An affected open socket receives a generic
`access_denied` event and closes with code 4403. Idle party sockets recheck at the
normal one-second tick; ranked sockets at quarter-second ticks. No answer or game
state is sent after a failed check. A request already in progress when a rule
changes is not retroactively undone.

Exempt staff sockets remain connected. Demoting staff restores applicable blocks
on the next action/push/tick; a reconnect is not needed. Socket decisions use the
durable current session so a stale authenticated scope cannot bypass guest rules.

Disconnect follows existing game policy: queue connections close normally;
ranked reconnect grace and existing clocks determine the result; party presence
leases, host departure and minimum-player rules apply. The feature does not delay
deadlines, award wins, alter Elo, or impose account sanctions. Keep `party_clock`
and `ranked_clock` running as documented. Presence/queue cleanup can take its
existing lease period rather than deleting active matches immediately.

HTTP failures are 403 with generic `detail` and `code` (`ip_restricted` or
`client_ip_unavailable`), never internal reasons or administrator identity.
The account-notices socket enforces login restrictions as well as account updates.

## Trusted proxy configuration (required before a proxied deployment)

In production, `IP_TRUSTED_PROXIES` defaults to empty. With no configured proxies, the actual
transport peer (`REMOTE_ADDR` / ASGI `scope.client`) is the client; arbitrary
`X-Forwarded-For`, `Forwarded` and `X-Real-IP` cannot override it. This works for
direct local development. In DEBUG mode only, Django additionally trusts exactly
`127.0.0.2/32`. The local Vite proxy binds outgoing HTTP/WebSocket connections to
that alias and replaces incoming forwarded-IP headers with the actual browser
socket peer. Localhost browser peers (`127.0.0.1` / `::1`) remain distinct, and
LAN clients retain their actual IP for restriction enforcement. Do not trust the
whole loopback or LAN network. This exact development addition is absent in
production. See [LAN startup and troubleshooting](../README.md#access-from-another-device-on-your-lan-windows).

For a reverse proxy, set a comma-separated list of actual proxy IPs or strict
CIDR networks, for example `IP_TRUSTED_PROXIES=10.0.0.10/32,2001:db8:ffff::10/128`
(replace these documentation addresses with your infrastructure). Trust only
networks you control; `/0` and malformed configuration are rejected at startup.
Keep the application reachable only through those proxies using network rules.

The first trusted edge must replace incoming client-supplied X-Forwarded-For with
the real socket client. Later trusted hops append their real upstream peers. The
application validates the whole header, then walks right to left to find the
first untrusted hop. Untrusted peers' forwarding headers are ignored. Missing,
malformed, overlong or all-trusted chains fail closed for protected activities.
HTTP and WebSocket parsing share the same resolver. Configure WebSocket forwarding
identically to HTTP. Other forwarding header formats are intentionally ignored.

Preserve the real transport peer in Django/ASGI. Do not enable Daphne
`--proxy-headers` or another server/middleware that replaces the peer before this
resolver. Otherwise the application cannot authenticate the forwarding hop.
Configure TLS proxy headers separately and securely as described in the README.
Never trust loopback just to make missing forwarding headers pass validation.
Confirm client identity through the deployed proxy chain before public launch.

This feature does not replace edge rate limiting or change DRF's throttle identity
policy. Avoid full query-string logging for the management endpoints: search can
contain an internal reason or IP. Restriction decisions do not add IP logs.

## Staff access and recovery

Administrators can blacklist their own IP without adding a whitelist first, and
can move or delete a matching whitelist while the blacklist remains active. Their
staff exemption preserves access; ordinary players sharing that address remain
subject to the rule. Ordinary moderators remain unable to manage either list.
There is no blanket localhost exemption. Blacklisting configured trusted
infrastructure is still rejected; target the end-client address instead.

The role exemption applies to IP blacklist rules. Missing or malformed trusted
proxy identity still fails network validation, including during staff sign-in.

An operator with server shell access can add/update an audited exception using an
existing active administrator (from `backend/`, using the project's environment):

```powershell
..\.venv\Scripts\python.exe manage.py ip_access_recover 203.0.113.9 --administrator YOUR_ADMIN_USERNAME --reason "Operator recovery: verified current client IP"
```

Use the real client IP. This is a server-local command, not a public recovery API.
It changes only this feature's whitelist; it cannot reverse account sanctions or
create/grant administrator accounts. Correct a malformed proxy configuration on
the server first; a whitelist cannot repair an unverifiable transport identity.

## Storage, API and audit

`moderation.IPAccessEntry` is introduced by migration `0007_ipaccessentry`. It
stores normalized address, list kind, six selectable booleans plus the retained
legacy ranked flag, reason, UTC expiry, creation/
update timestamps and actors. Database constraints enforce per-list uniqueness,
valid list configuration and expiry after creation. Apply normal additive
migrations before starting updated workers; do not recreate existing databases.

Base path: `/api/moderation/workspace/administration/ip-access/`

| Endpoint | Methods |
| --- | --- |
| `blacklist/`, `whitelist/` | GET paginated list (`q`, `page`), POST create |
| `blacklist/<uuid>/`, `whitelist/<uuid>/` | GET detail, POST edit, DELETE |

Shared fields: `address`, `reason`. Blacklist writes additionally require
`activities` (keys: registration, login, singleplayer, parties, submissions,
community), `duration` (`temporary` or `indefinite`) and `expires_at` (future ISO
timestamp for temporary; null/omitted for indefinite). Responses include active/
expired status, actors and timestamps. All endpoints use the existing administrator
permission service; writes use normal session authentication and CSRF protection.

Every create/edit/delete writes existing moderation `Activity` records with actor,
timestamp and before/after values. Audit data is administrator-only and is not
attached to a player activity feed. Deleting a rule affects no users, matches or
images. Audit records retain the deleted rule's values.

Tests are in `backend/tests/test_ip_access.py` and
`frontend/src/test/ip-management.test.tsx`. Run the full existing suites as well.
Use isolated test databases, including file-backed SQLite or PostgreSQL for real
concurrent duplicate-writer coverage. No external services/dependencies were added.
