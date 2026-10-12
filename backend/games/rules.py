from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModeRules:
    id: str
    name: str
    account_required: bool
    reveal_seconds: int = 30
    guess_limit: int | None = None
    incorrect_cooldown_seconds: int = 0
    incorrect_penalty: int = 0
    max_correct_score: int | None = None
    decisive_wins_to_finish: int | None = None
    available: bool = False
    rounds_per_session: int | None = None


MODES = (
    ModeRules("ranked", "Ranked Duel", True, guess_limit=1, decisive_wins_to_finish=4),
    ModeRules(
        "singleplayer",
        "Singleplayer",
        False,
        reveal_seconds=45,
        max_correct_score=1000,
        available=True,
        rounds_per_session=5,
    ),
    ModeRules(
        "party",
        "Parties",
        False,
        incorrect_cooldown_seconds=2,
        incorrect_penalty=50,
        max_correct_score=1000,
        available=True,
        rounds_per_session=10,
    ),
)


def public_rules():
    return [asdict(mode) for mode in MODES]
