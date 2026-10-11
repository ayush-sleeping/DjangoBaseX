"""A URLconf whose enforcement is known, used only to prove the route checker can fail."""

from django.http import Http404
from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class Gated(APIView):
    """Default permissions (IsAuthenticated): must pass the checker."""

    def get(self, request, pk):
        return Response({})


class Open(APIView):
    """The mistake the checker exists for."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({})


class LooksUpFirst(APIView):
    """Answers 404 before authorization runs, as a lookup-then-check view does."""

    def initial(self, request, *args, **kwargs):
        raise Http404


urlpatterns = [
    path("api/gated/<int:pk>/", Gated.as_view(), name="gated"),
    path("api/open/", Open.as_view(), name="open"),
    path("api/lookup-first/<uuid:public_id>/", LooksUpFirst.as_view(), name="lookup-first"),
]
