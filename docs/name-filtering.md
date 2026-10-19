# Player name filtering

New player-assigned usernames and display names are checked on registration,
username changes, and profile edits. Existing accounts are not scanned or changed.
Guest party labels are server-generated; legacy supplied guest names are ignored.

`better-profanity==0.7.0` is a small MIT-licensed, pure-Python package with no runtime
dependencies. Its current PyPI release is from November 2020; it is mature but not
actively releasing. We chose it over NLP/model-based alternatives to avoid models,
downloads at runtime, and unrelated dependencies, and verified it on Python 3.13.7.
Review future package maintenance before upgrading or replacing it.

The adapter in `accounts/name_filter.py` keeps whole-word matching, allows neutral
identity/belief terms, and handles NFKC normalization, common leetspeak (upstream),
CamelCase boundaries, simple numeric suffixes, invisible formatting, and spelled-out
letter sequences separated by spaces/dots/underscores/hyphens. It deliberately
does not search arbitrary substrings or scan all possible obfuscations. This is an
English-oriented basic filter, not a guarantee against all abusive names.

Joined-word detection supplements upstream whole-word checks using its existing
filtered vocabulary and leetspeak mappings. A token composed entirely of two or
more prohibited terms is rejected, including repetitions. A run of two terms of
at least four characters each is also detected at either edge of a longer token.
Single embedded fragments are not enough; short-term edge matching is deliberately
excluded so ordinary words such as assassin, assassination, Scunthorpe, Dickinson,
and Cocktail remain allowed. The bounded segmentation checks each reachable
position once instead of using a potentially exponential repeated-alternation
regular expression. Package vocabulary/mapping access is confined to the adapter
and covered by regression tests for the pinned package version.

Only the authorized staff `change_names` operation uses `PlayerNamesInput` and its
unfiltered assignment path. Existing format, length, uniqueness, permission checks,
and audit logging still apply. A client flag, caller role, or self-service request
cannot select the exemption. Package policy and neutral exceptions should be
reviewed when false positives are reported; do not expose word lists in API errors.

Sources reviewed:

- [PyPI metadata and behavior](https://pypi.org/project/better-profanity/)
- [Upstream repository and limitations](https://github.com/snguyenthanh/better_profanity)
