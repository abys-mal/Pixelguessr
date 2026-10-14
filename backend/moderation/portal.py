"""A password proof for notices/appeals only; it never authenticates gameplay."""

from django.contrib.auth.hashers import check_password
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import User

from .workspace import submit_appeal
from .workspace_serializers import PlayerAppeal, PlayerNotice


class NoticeAuthentication(SessionAuthentication):
    def authenticate(self, request):
        regular = super().authenticate(request)
        if regular:
            return regular
        proof = request._request.session.get("notice_access", {})
        if timezone.now().timestamp() - proof.get("time", 0) >= 900:
            return None
        user = User.objects.filter(pk=proof.get("user"), is_active=True).first()
        if not user or not constant_time_compare(
            proof.get("hash", ""), user.get_session_auth_hash()
        ):
            return None
        self.enforce_csrf(request)
        return user, None


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class NoticeLogin(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        username = serializers.CharField(max_length=150).run_validation(
            request.data.get("username")
        )
        password = serializers.CharField(max_length=128, trim_whitespace=False).run_validation(
            request.data.get("password")
        )
        user = User.objects.filter(username__iexact=username, is_active=True).first()
        if not user:
            User().set_password(password)  # Similar password-hashing work for unknown usernames.
            raise PermissionDenied("Invalid username or password.")
        if not check_password(password, user.password):
            raise PermissionDenied("Invalid username or password.")
        request.session.cycle_key()
        request.session["notice_access"] = {
            "user": str(user.pk),
            "hash": user.get_session_auth_hash(),
            "time": timezone.now().timestamp(),
        }
        return Response({"username": user.username})


@method_decorator(never_cache, name="dispatch")
class MyNotices(APIView):
    authentication_classes = [NoticeAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "username": request.user.username,
                "sanctions": PlayerNotice(
                    request.user.sanctions.order_by("-starts_at"), many=True
                ).data,
                "appeals": PlayerAppeal(request.user.appeals.all(), many=True).data,
            }
        )

    def delete(self, request):
        request.session.pop("notice_access", None)
        return Response(status=204)


class SubmitAppeal(MyNotices):
    def post(self, request, pk):
        explanation = serializers.CharField(max_length=4000).run_validation(
            request.data.get("explanation")
        )
        return Response(PlayerAppeal(submit_appeal(request.user, pk, explanation)).data, status=201)
