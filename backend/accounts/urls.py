from django.urls import path

from .views import (
    AccountSettingsView,
    ChangeEmailView,
    ChangePasswordView,
    ChangeUsernameView,
    CsrfView,
    LoginView,
    LogoutView,
    MeView,
    ProfileView,
    RegisterView,
)

urlpatterns = [
    path("settings/", AccountSettingsView.as_view()),
    path("change-username/", ChangeUsernameView.as_view()),
    path("change-email/", ChangeEmailView.as_view()),
    path("change-password/", ChangePasswordView.as_view()),
    path("csrf/", CsrfView.as_view()),
    path("register/", RegisterView.as_view()),
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("me/", MeView.as_view()),
    path("profiles/<str:username>/", ProfileView.as_view()),
]
