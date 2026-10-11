from django.contrib.auth.backends import ModelBackend


class AccountBackend(ModelBackend):
    def user_can_authenticate(self, user):
        from moderation.services import account_restrictions

        return super().user_can_authenticate(user) and not account_restrictions(user)["blocked"]
