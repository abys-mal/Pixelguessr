from django.urls import path

from .views import ModeList

urlpatterns = [path("", ModeList.as_view())]
