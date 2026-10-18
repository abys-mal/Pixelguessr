from django.urls import path

from .contribution_views import ContributionDetail, ContributionPreview, Contributions
from .views import CategoryList, MySubmissions, PrivatePreview, PublicCatalog

urlpatterns = [
    path("contributions/", Contributions.as_view()),
    path("contributions/<uuid:pk>/", ContributionDetail.as_view()),
    path("contributions/<uuid:pk>/preview/", ContributionPreview.as_view()),
    path("categories/", CategoryList.as_view()),
    path("catalog/", PublicCatalog.as_view()),
    path("submissions/", MySubmissions.as_view()),
    path("submissions/<uuid:pk>/preview/", PrivatePreview.as_view()),
]
