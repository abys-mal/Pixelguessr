from django.contrib.auth import login, logout, update_session_auth_hash
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import User
from .permissions import AccountAccess
from .serializers import (
    EmailChangeSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PublicProfileSerializer,
    RegisterSerializer,
    SettingsSerializer,
    UsernameChangeSerializer,
    UserSerializer,
)


class CsrfView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "csrf"

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


# SessionAuthentication only checks CSRF for authenticated requests; login and
# registration need explicit protection too, including anonymous requests.
@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                user = serializer.save()
        except IntegrityError:
            return Response({"detail": "Username or email is unavailable."}, status=400)
        login(request, user, backend="accounts.backends.AccountBackend")
        return Response({"user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        login(request, user)
        return Response({"user": UserSerializer(user).data})


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    # Flush the current cookie session even when authentication expired or was blocked.
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from .session_state import session_payload

        return Response(session_payload(request))

    def patch(self, request):
        # Apply normal account permission to edits; reads are used for warning UI.
        from .permissions import AccountAccess

        permission = AccountAccess()
        if not permission.has_permission(request, self):
            return Response({"detail": permission.message}, status=403)
        serializer = SettingsSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"user": UserSerializer(request.user).data})


class ProfileView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, username):
        from django.shortcuts import get_object_or_404

        user = get_object_or_404(User, username=username, is_active=True)
        return Response(PublicProfileSerializer(user).data)


@method_decorator(never_cache, name="dispatch")
class AccountSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .services import settings_payload

        return Response(settings_payload(request.user))


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters(), name="dispatch")
class AccountChangeView(APIView):
    permission_classes = [IsAuthenticated, AccountAccess]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "account_change"
    operation = None
    serializer_class = None

    def post(self, request):
        from .services import change_account, settings_payload

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = change_account(request.user.pk, self.operation, serializer.validated_data)
        except IntegrityError:
            # Database constraints also handle concurrent claims by different users.
            return Response({"detail": "Username or email is unavailable."}, status=400)
        if self.operation == "password":
            update_session_auth_hash(request, user)
        return Response({"settings": settings_payload(user)})


class ChangeUsernameView(AccountChangeView):
    operation = "username"
    serializer_class = UsernameChangeSerializer


class ChangeEmailView(AccountChangeView):
    operation = "email"
    serializer_class = EmailChangeSerializer


class ChangePasswordView(AccountChangeView):
    operation = "password"
    serializer_class = PasswordChangeSerializer


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters(), name="dispatch")
class VerifyClosurePasswordView(APIView):
    permission_classes = [IsAuthenticated, AccountAccess]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "account_change"

    def post(self, request):
        from .lifecycle import verify_password
        from .serializers import ClosurePasswordSerializer

        serializer = ClosurePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verify_password(request.user.pk, serializer.validated_data["current_password"])
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters(), name="dispatch")
class CloseAccountView(APIView):
    permission_classes = [IsAuthenticated, AccountAccess]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "account_change"

    def post(self, request):
        from .lifecycle import close_account
        from .serializers import CloseAccountSerializer

        serializer = CloseAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        close_account(request.user.pk, **serializer.validated_data)
        logout(request)
        return Response({"detail": "Your account has been voluntarily closed. You are signed out."})
