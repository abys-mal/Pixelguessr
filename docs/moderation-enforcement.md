# Moderation gameplay enforcement

Current policy supersedes historical warning gates and suspension login blocks.

| Sanction | Singleplayer | Parties | Ranked | Image submissions | Normal account |
| --- | --- | --- | --- | --- | --- |
| Unacknowledged warning | Allowed | Allowed | Allowed | Allowed | Allowed |
| Probation | Allowed | Allowed | Blocked | Blocked | Allowed |
| Suspension | Allowed | Blocked | Blocked | Blocked | Allowed |
| Closure | Blocked | Blocked | Blocked | Blocked | Blocked |

Kinds coexist. Each activity applies all applicable restrictions. Warnings only
create notices; acknowledgment hides their homepage banner without deleting history.
Active means started, not reversed, and not expired. The existing unique-active-type
validation, warning expiry, appeal cooldowns, permissions and audit records remain.

## Durable game transitions

Sanction saves take the existing ranked writer gate, then the player writer lock,
then any affected party locks. Native moderation commands and Admin revocation use
the same order. Enforcement and its audit records commit in the same transaction.
A failed sanction/audit write rolls back its game changes as well.

Probation, suspension and closure clear queued ranked entry/presence and settle an
active duel as a forfeit, using existing completion/Elo logic and its durable
exactly-once guard. The opponent wins. Moderation reconciliation runs before normal
round/disconnect settlement, so an active restriction is not treated as No Contest.
If ordinary completion already committed before a sanction becomes active, the
completed result remains unchanged.

A suspended/closed party host ends the party immediately. Every membership is marked
left, active rounds end, and stored scores/history remain. There is no host transfer.
A restricted non-host is marked left with an explicit reason; other members continue,
including a sole remaining host. Warning/probation do not change party membership.
Singleplayer is untouched by warning, probation and suspension.

On-commit Channels invalidations push fresh, permission-checked snapshots to account,
ranked and party sockets. These callbacks are robust: unavailable delivery does not
undo or misreport an already committed sanction. Existing game socket reads/clocks
reconcile durable restrictions, including future-dated sanctions and process restarts.
The normal-session account socket rechecks durable state every second to catch
expiry, scheduling, lost messages and separate in-memory development processes.
The browser reconnects automatically and polls `/api/auth/me/` every five seconds
when disconnected; focus/online also refreshes. A stale HTTP refresh cannot overwrite
a newer live account event.

Reversal/expiry restores entry eligibility and updates notices. It does not resurrect
forfeited duels, removed memberships or ended parties. Server action/read checks
prevent reconnecting clients from bypassing restrictions. Existing clocks must keep
running for scheduled game transitions without connected clients.

## Account interface and authentication

Account Notices (`/account-notices`) uses the normal authenticated session and includes public sanction
history, dates, acknowledgment, eligible appeals and appeal decisions. Private
moderator notes remain staff-only. Existing warning/30-day probation/90-day suspension
appeal cooldowns begin at the latest upheld decision timestamp and follow the
player and type across replacements. Pending appeals block duplicates without
starting cooldowns; approved/changed appeals do not start them. Closure is nonappealable
and only an administrator may reverse it.

Suspension keeps the normal login/session. The separate notice-login endpoint
and limited proof implementation are removed. The dedicated Account Notices page
needs no second login; Account Settings links to it without duplicating its forms. Closed-account
credentials are verified before displaying `Your account has been closed.` Existing
closed sessions receive the same message and cannot fall back to anonymous gameplay
without signing out. This is an account restriction, not a device ban.

Homepage banners prioritize suspension, probation, then unacknowledged warnings,
show expiry when present, and link to Account Notices. Reports/Appeals use matching inbox
alignment, spacing and responsive grids without redesigning the workspace.

## Verification and manual playtest

Automated coverage includes the complete activity matrix, credential disclosure,
active duel/party transitions, Elo idempotency, scheduled restrictions, preserved
singleplayer, notice privacy/priority/expiry/acknowledgment, normal-session appeals,
live account changes and file-backed SQLite writer races. Existing permissions,
replacement/cooldown/audit tests remain in the full suites. No migration is needed.

Use synthetic accounts in a separate development database:

1. Sign in as a player and moderator in separate browser profiles. Keep the player's
   homepage open. Issue a warning: the banner appears without refresh, gameplay stays
   available. Acknowledge in Account Notices; the banner disappears and history remains.
2. Start a duel. Apply probation/suspension/closure. Both clients see the forfeit,
   the opponent wins and each rating changes once, including after reconnect/refresh.
3. Suspend/close a party host: everyone leaves with a host-specific explanation.
   Suspend a non-host: only that player leaves; remaining players can continue.
   Apply probation/warning to either role: no party interruption.
4. Keep singleplayer open during probation/suspension and finish the round. Verify
   Settings and eligible appeals remain accessible; ranked/submissions stay denied.
5. Reverse or expire a restriction while online: banner and new-entry eligibility
   update, completed results stay settled. Check closure credentials and admin-only
   reversal. Check Reports/Appeals at desktop and narrow mobile widths.

Local verification uses SQLite/in-memory Channels. PostgreSQL/Redis deployment and
multi-worker transport should also be checked in the deployment environment; no new
infrastructure or dependencies are required by this change.
