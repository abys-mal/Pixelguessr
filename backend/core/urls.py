from django.urls import path

from .views import live, ready

urlpatterns = [path("live/", live), path("ready/", ready)]
