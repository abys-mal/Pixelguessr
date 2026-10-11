from django.contrib.auth import login, logout
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from moderation.services import account_restrictions

from .models import User
from .serializers import (
    LoginSerializer,
    PublicProfileSerializer,
    RegisterSerializer,
    SettingsSerializer,
    UserSerializer,
)


class CsrfView(APIView):
    permission_classes = [AllowAny]

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


class LogoutView(APIView):
    # Suspended accounts must still be able to end their session.
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"user": None, "restrictions": None})
        return Response(
            {
                "user": UserSerializer(request.user).data,
                "restrictions": account_restrictions(request.user),
            }
        )

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
