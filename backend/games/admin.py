from django.contrib import admin

from .models import Guess, GuestIdentity, Match, Participant, Round, RoundPlayerState


class ScaffoldAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (Match, GuestIdentity, Participant, Round, RoundPlayerState, Guess):
    admin.site.register(model, ScaffoldAdmin)
