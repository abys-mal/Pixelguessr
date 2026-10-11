from django.urls import path

from .views import CategoryList, MySubmissions, PrivatePreview, PublicCatalog

urlpatterns = [
    path("categories/", CategoryList.as_view()),
    path("catalog/", PublicCatalog.as_view()),
    path("submissions/", MySubmissions.as_view()),
    path("submissions/<uuid:pk>/preview/", PrivatePreview.as_view()),
]
