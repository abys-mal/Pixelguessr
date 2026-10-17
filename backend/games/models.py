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
        ABORTED = "aborted", "Aborted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mode = models.CharField(max_length=12, choices=Mode)
    status = models.CharField(max_length=12, choices=Status, default=Status.WAITING)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    elo_applied_at = models.DateTimeField(null=True, blank=True)
    ranked_revision = models.PositiveIntegerField(default=0)
    ranked_winner = models.ForeignKey(
        "Participant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ranked_victories",
    )
    ranked_outcome = models.CharField(max_length=16, blank=True)
    ranked_message = models.CharField(max_length=240, blank=True)
    party_round_limit = models.PositiveSmallIntegerField(default=0, editable=False)
    party_abort_reason = models.CharField(max_length=24, blank=True, editable=False)
    # Legacy one-round games remain historical; new singleplayer games use five.
    singleplayer_round_limit = models.PositiveSmallIntegerField(default=1, editable=False)
    singleplayer_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    singleplayer_revision = models.PositiveIntegerField(default=0, editable=False)

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
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    guest = models.ForeignKey(GuestIdentity, null=True, blank=True, on_delete=models.PROTECT)
    party_member = models.ForeignKey("PartyMember", null=True, blank=True, on_delete=models.PROTECT)
    identity_deleted = models.BooleanField(default=False)
    total_score = models.PositiveIntegerField(default=0)
    decisive_wins = models.PositiveSmallIntegerField(default=0)
    rating_before = models.PositiveIntegerField(null=True, blank=True)
    rating_after = models.PositiveIntegerField(null=True, blank=True)
    rating_delta = models.IntegerField(null=True, blank=True)
    rated_matches_before = models.PositiveIntegerField(null=True, blank=True)
    ranked_last_seen = models.DateTimeField(null=True, blank=True)
    ranked_disconnected_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(user__isnull=False, guest__isnull=True, identity_deleted=False)
                | models.Q(user__isnull=True, guest__isnull=False, identity_deleted=False)
                | models.Q(user__isnull=True, guest__isnull=True, identity_deleted=True),
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
        if (
            self.match_id
            and self.match.mode == Match.Mode.RANKED
            and not self.user_id
            and not self.identity_deleted
        ):
            raise ValidationError("Ranked participants require registered accounts.")


class Round(models.Model):
    class Outcome(models.TextChoices):
        SOLVED = "solved", "Solved"
        FORFEITED = "forfeited", "Forfeited"
        EXPIRED = "expired", "Expired"
        COMPLETE = "complete", "Complete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="rounds")
    image = models.ForeignKey(
        "library.ImageSubmission", on_delete=models.SET_NULL, null=True, blank=True
    )
    number = models.PositiveIntegerField()
    start_request_id = models.UUIDField(null=True, blank=True, unique=True)
    grid_size = models.PositiveSmallIntegerField(default=20)
    reveal_duration_seconds = models.PositiveSmallIntegerField(default=45)
    reveal_order = models.JSONField(default=list, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    answer_snapshot = models.CharField(max_length=120, blank=True, editable=False)
    synonyms_snapshot = models.JSONField(default=list, editable=False)
    image_storage_name = models.CharField(max_length=500, blank=True, editable=False)
    image_metadata_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    reveal_seed = models.UUIDField(default=uuid.uuid4, editable=False)
    reveal_started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=12, choices=Outcome, blank=True, default="")
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
    ranked_guessed_at = models.DateTimeField(null=True, blank=True)
    ranked_request_id = models.UUIDField(null=True, blank=True, unique=True)
    score = models.IntegerField(default=0)  # Round scores may be negative.
    solved_at = models.DateTimeField(null=True, blank=True)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    incorrect_count = models.PositiveIntegerField(default=0)
    total_before = models.PositiveIntegerField(default=0)
    total_after = models.PositiveIntegerField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    solve_revealed_count = models.PositiveIntegerField(null=True, blank=True)

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


class Party(models.Model):
    class Status(models.TextChoices):
        LOBBY = "lobby", "Lobby"
        PLAYING = "playing", "Playing"
        COMPLETE = "complete", "Complete"
        CLOSED = "closed", "Closed"
        ABORTED = "aborted", "Aborted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=6, unique=True)
    create_request_id = models.UUIDField(unique=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.LOBBY)
    reveal_seconds = models.PositiveSmallIntegerField(default=30)
    round_limit = models.PositiveSmallIntegerField(default=10)
    host = models.ForeignKey(
        "PartyMember", null=True, on_delete=models.SET_NULL, related_name="hosted"
    )
    current_match = models.ForeignKey(
        Match, null=True, on_delete=models.SET_NULL, related_name="parties"
    )
    revision = models.PositiveIntegerField(default=1)
    message = models.CharField(max_length=240, blank=True)
    end_reason = models.CharField(max_length=24, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reveal_seconds__in=[15, 30, 45, 60]), name="party_valid_reveal"
            ),
            models.CheckConstraint(
                condition=models.Q(round_limit__in=[5, 10, 15, 20]), name="party_valid_round_limit"
            ),
        ]


class PartyMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    guest = models.ForeignKey(GuestIdentity, null=True, blank=True, on_delete=models.PROTECT)
    identity_deleted = models.BooleanField(default=False)
    display_name = models.CharField(max_length=40)
    name_key = models.CharField(max_length=120)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField()
    left_at = models.DateTimeField(null=True, blank=True)
    departure_reason = models.CharField(max_length=12, blank=True)
    banned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(user__isnull=False, guest__isnull=True, identity_deleted=False)
                | models.Q(user__isnull=True, guest__isnull=False, identity_deleted=False)
                | models.Q(user__isnull=True, guest__isnull=True, identity_deleted=True),
                name="party_member_one_identity",
            ),
            models.UniqueConstraint(
                fields=["party", "user"],
                condition=models.Q(user__isnull=False),
                name="party_member_unique_user",
            ),
            models.UniqueConstraint(
                fields=["party", "guest"],
                condition=models.Q(guest__isnull=False),
                name="party_member_unique_guest",
            ),
            models.UniqueConstraint(
                fields=["party", "name_key"],
                condition=models.Q(left_at__isnull=True),
                name="party_member_unique_name",
            ),
        ]


class PartyCommand(models.Model):
    request_id = models.UUIDField(primary_key=True)
    party = models.ForeignKey(Party, on_delete=models.CASCADE)
    member = models.ForeignKey(PartyMember, on_delete=models.CASCADE)
    action = models.CharField(max_length=12)
    target = models.ForeignKey(
        PartyMember, null=True, blank=True, on_delete=models.PROTECT, related_name="removals"
    )
    prevent_rejoin = models.BooleanField(default=False)


class RankedGate(models.Model):
    # One persistent writer gate, shared by every process and ranked mutation.
    revision = models.PositiveBigIntegerField(default=0)


class RankedQueue(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE
    )
    ticket = models.UUIDField(null=True, blank=True, unique=True)
    queued_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    rating_snapshot = models.PositiveIntegerField(default=1000)
    match = models.ForeignKey(Match, null=True, blank=True, on_delete=models.PROTECT)


class RankedConnection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    match = models.ForeignKey(Match, null=True, blank=True, on_delete=models.CASCADE)
    queue_ticket = models.UUIDField(null=True, blank=True)
    last_seen = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["match", "user"]),
            models.Index(fields=["queue_ticket", "user"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(match__isnull=False, queue_ticket__isnull=True)
                | models.Q(match__isnull=True, queue_ticket__isnull=False),
                name="ranked_connection_one_scope",
            )
        ]
