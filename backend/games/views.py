from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .rules import public_rules


class ModeList(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"phase": 2, "gameplay_available": True, "modes": public_rules()})
