from django.contrib.auth.backends import ModelBackend


class AccountBackend(ModelBackend):
    def authenticate(
        self, request, username=None, password=None, *, include_closed=False, **kwargs
    ):
        from moderation.services import active_sanctions

        from .models import User

        if username is None or password is None:
            return None
        try:
            user = User._default_manager.get_by_natural_key(username)
        except User.DoesNotExist:
            # Match Django's missing-user password work to limit timing disclosure.
            User().set_password(password)
            return None
        if user.check_password(password) and (
            self.user_can_authenticate(user)
            or (include_closed and active_sanctions(user).filter(kind="closed").exists())
        ):
            # include_closed is used only by the login serializer, which rejects
            # closure before LoginView can establish a session.
            return user

    def user_can_authenticate(self, user):
        from moderation.services import account_restrictions

        return super().user_can_authenticate(user) and not account_restrictions(user)["blocked"]
