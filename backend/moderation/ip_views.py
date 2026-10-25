from django.db.models import Q
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.client_ip import ClientIPError, normalize_ip

from .administration_views import AdministratorView, page, validated
from .ip_management import BlacklistInput, IPInput, delete_entry, entry_payload, save_entry
from .models import IPAccessEntry


class IPList(AdministratorView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if kwargs["list_kind"] not in IPAccessEntry.ListKind.values:
            raise NotFound("IP list not found.")

    def get(self, request, list_kind):
        rows = IPAccessEntry.objects.filter(list_kind=list_kind).select_related(
            "created_by", "updated_by"
        )
        query = request.query_params.get("q", "").strip()[:150]
        if query:
            try:
                normalized = normalize_ip(query)
            except ClientIPError:
                normalized = query
            rows = rows.filter(Q(address__icontains=normalized) | Q(reason__icontains=query))
        return page(request, rows, entry_payload)

    def post(self, request, list_kind):
        data = validated(BlacklistInput if list_kind == "blacklist" else IPInput, request.data)
        return Response(
            entry_payload(save_entry(request.user, list_kind, data)),
            status=201,
        )


class IPDetail(IPList):
    def get(self, request, list_kind, pk):
        from django.shortcuts import get_object_or_404

        return Response(
            entry_payload(
                get_object_or_404(
                    IPAccessEntry.objects.select_related("created_by", "updated_by"),
                    list_kind=list_kind,
                    pk=pk,
                )
            )
        )

    def post(self, request, list_kind, pk):
        data = validated(BlacklistInput if list_kind == "blacklist" else IPInput, request.data)
        return Response(entry_payload(save_entry(request.user, list_kind, data, pk=pk)))

    def delete(self, request, list_kind, pk):
        delete_entry(request.user, list_kind, pk)
        return Response(status=204)
