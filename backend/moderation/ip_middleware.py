import re

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from .ip_rules import IPAccessDenied, enforce_request


def activity_for_http(path, method):
    if method == "POST" and (
        re.fullmatch(r"/api/parties/[^/]+/leave/", path)
        or re.fullmatch(r"/api/ranked/matches/[^/]+/leave/", path)
        or path == "/api/ranked/queue/cancel/"
        or re.fullmatch(r"/api/games/singleplayer/rounds/[^/]+/forfeit/", path)
    ):
        return None, True  # Cleanup only; normal ownership, CSRF and account checks still apply.
    if method == "POST":
        if path in {"/api/auth/register/", "/admin/accounts/user/add/"}:
            return "registration", False
        if path in {"/api/auth/login/", "/admin/login/"}:
            return "login", False
        if path in {
            "/api/library/contributions/",
            "/api/library/submissions/",
            "/admin/library/imagesubmission/add/",
        } or re.fullmatch(r"/api/moderation/workspace/administration/imports/[^/]+/", path):
            return "submissions", False
        if path == "/api/moderation/reports/":
            return "community", False
    for prefix, activity in (
        ("/api/games/singleplayer/", "singleplayer"),
        ("/api/parties/", "parties"),
        ("/api/ranked/queue/", "ranked"),
        ("/api/ranked/matches/", "ranked"),
    ):
        if path.startswith(prefix):
            return activity, False
    return None, False


class IPAccessMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Both login handlers enforce after credentials are verified, so staff
        # can sign in from blocked networks without trusting a supplied username.
        login_path = request.path_info in {"/api/auth/login/", "/admin/login/"}
        authenticated = bool(request.user.is_authenticated)
        if login_path and not authenticated:
            return None
        activity, cleanup = activity_for_http(request.path_info, request.method)
        if cleanup and not authenticated:
            return None
        if activity is None and not authenticated:
            return None
        try:
            enforce_request(request, None if login_path else activity, authenticated=authenticated)
        except IPAccessDenied as exc:
            if exc.login_restricted and request.path_info in {
                "/api/auth/me/",
                "/api/auth/csrf/",
                "/api/auth/logout/",
                "/api/auth/login/",
                "/admin/login/",
            }:
                # Session checks report the new signed-out state. Login still
                # verifies the submitted credentials, allowing exempt staff in.
                return None
            response = JsonResponse(exc.detail, status=403)
            response["Cache-Control"] = "private, no-store"
            response["Vary"] = "Cookie"
            return response
        return None
