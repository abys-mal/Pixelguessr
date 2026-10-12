"""Ranked tuning lives here; settings.RANKED_CONFIG may override these defaults."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from django.conf import settings

DEFAULTS = {
    "starting_elo": 1000,
    "rating_floor": 100,
    "early_k": 40,
    "established_k": 24,
    "early_matches": 20,
    "wins_to_finish": 4,
    "reveal_seconds": 45,
    "countdown_seconds": 3,
    "results_seconds": 5,
    "grace_seconds": 30,
    "coincidence_seconds": 2,
    "presence_seconds": 12,
    "search_windows": [(0, 100), (15, 150), (30, 250), (60, 400), (90, 600), (120, 800)],
    "tiers": [(1200, "bronze"), (1400, "silver"), (1600, "gold"), (1800, "diamond")],
}


def rule(name):
    return getattr(settings, "RANKED_CONFIG", {}).get(name, DEFAULTS[name])


def starting_rating():
    return rule("starting_elo")


def tier(rating):
    return next((name for minimum, name in reversed(rule("tiers")) if rating >= minimum), None)


def search_window(seconds):
    seconds = max(0, seconds)
    return min(
        800,
        next(limit for minimum, limit in reversed(rule("search_windows")) if seconds >= minimum),
    )


def elo_after(rating, opponent, won, previous_matches):
    with localcontext() as context:
        context.prec = 32
        difference = Decimal(opponent - rating) / 400
        expected = (
            Decimal(0)
            if difference > 100
            else Decimal(1)
            if difference < -100
            else 1 / (1 + Decimal(10) ** difference)
        )
        k = rule("early_k") if previous_matches < rule("early_matches") else rule("established_k")
        value = Decimal(rating) + k * (int(won) - expected)
        return max(rule("rating_floor"), int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
