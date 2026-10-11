import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Match(models.Model):
    class Mode(models.TextChoices):
        SINGLEPLAYER = "singleplayer", "Singleplayer"
        PARTY = "party", "Parties"
        RANKED = "ranked", "Ranked Duel"

    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        ACTIVE = "active", "Active"
        COMPLETE = "complete", "Complete"
        ABANDONED = "abandoned", "Abandoned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mode = models.CharField(max_length=12, choices=Mode)
    status = models.CharField(max_length=12, choices=Status, default=Status.WAITING)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    elo_applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["mode", "status", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(elo_applied_at__isnull=True)
                | models.Q(mode="ranked", status="complete", completed_at__isnull=False),
                name="elo_only_on_completed_ranked",
            )
        ]


class GuestIdentity(models.Model):
    # Future guest tokens belong in signed server sessions, never in fake Users.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()


class Participant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    guest = models.ForeignKey(GuestIdentity, null=True, blank=True, on_delete=models.PROTECT)
    total_score = models.PositiveIntegerField(default=0)
    decisive_wins = models.PositiveSmallIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(user__isnull=False, guest__isnull=True)
                | models.Q(user__isnull=True, guest__isnull=False),
                name="participant_one_identity",
            ),
            models.UniqueConstraint(
                fields=["match", "user"],
                condition=models.Q(user__isnull=False),
                name="unique_match_user",
            ),
            models.UniqueConstraint(
                fields=["match", "guest"],
                condition=models.Q(guest__isnull=False),
                name="unique_match_guest",
            ),
        ]

    def clean(self):
        if self.match_id and self.match.mode == Match.Mode.RANKED and not self.user_id:
            raise ValidationError("Ranked participants require registered accounts.")


class Round(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="rounds")
    image = models.ForeignKey("library.ImageSubmission", on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    start_request_id = models.UUIDField(null=True, blank=True, unique=True)
    grid_size = models.PositiveSmallIntegerField(default=20)
    reveal_duration_seconds = models.PositiveSmallIntegerField(default=30)
    reveal_order = models.JSONField(default=list, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    answer_snapshot = models.CharField(max_length=120, blank=True, editable=False)
    synonyms_snapshot = models.JSONField(default=list, editable=False)
    image_storage_name = models.CharField(max_length=500, blank=True, editable=False)
    reveal_seed = models.UUIDField(default=uuid.uuid4, editable=False)
    reveal_started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    winner = models.ForeignKey(Participant, null=True, blank=True, on_delete=models.PROTECT)
    is_decisive = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["match", "number"], name="unique_match_round"),
            models.CheckConstraint(condition=models.Q(number__gte=1), name="round_number_positive"),
            models.CheckConstraint(
                condition=models.Q(is_decisive=False) | models.Q(winner__isnull=False),
                name="decisive_round_has_winner",
            ),
        ]

    def clean(self):
        if self.image_id and self.image.status != "approved":
            raise ValidationError("Rounds require approved images.")
        if self.winner_id and self.winner.match_id != self.match_id:
            raise ValidationError("The winner must belong to this match.")


class RoundPlayerState(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="player_states")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)  # Round scores may be negative.
    solved_at = models.DateTimeField(null=True, blank=True)
    cooldown_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["round", "participant"], name="unique_round_player_state"
            )
        ]

    def clean(self):
        if (
            self.round_id
            and self.participant_id
            and self.round.match_id != self.participant.match_id
        ):
            raise ValidationError("The participant must belong to the round's match.")


class Guess(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="guesses")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField()
    request_id = models.UUIDField(null=True, blank=True, unique=True)
    text = models.CharField(max_length=120)
    correct = models.BooleanField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["round", "participant", "sequence"], name="unique_guess_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1), name="guess_sequence_positive"
            ),
        ]

    def clean(self):
        if self.round_id and self.participant_id:
            if self.round.match_id != self.participant.match_id:
                raise ValidationError("The participant must belong to the round's match.")
            if self.round.match.mode == Match.Mode.RANKED and self.sequence != 1:
                raise ValidationError("Ranked permits only one guess per player per round.")
