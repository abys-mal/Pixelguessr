from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from rest_framework.pagination import PageNumberPagination


class ClampedPaginator(Paginator):
    def validate_number(self, number):
        try:
            return super().validate_number(number)
        except PageNotAnInteger:
            return 1
        except EmptyPage:
            return self.num_pages if int(number) > 0 else 1


class ResilientPageNumberPagination(PageNumberPagination):
    """Return the nearest valid page using the paginator's existing cached count."""

    django_paginator_class = ClampedPaginator

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data.update(
            page=self.page.number,
            page_size=self.page.paginator.per_page,
            total_pages=self.page.paginator.num_pages if self.page.paginator.count else 0,
        )
        return response

    def get_paginated_response_schema(self, schema):
        result = super().get_paginated_response_schema(schema)
        result["properties"].update(
            {key: {"type": "integer"} for key in ("page", "page_size", "total_pages")}
        )
        return result
