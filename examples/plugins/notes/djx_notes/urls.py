from django.urls import path

from .views import NoteViewSet

app_name = "notes"

# Mounted at /api/notes/ through registry.api_routes (wiring.py).
urlpatterns = [
    path("", NoteViewSet.as_view({"get": "list", "post": "create"}), name="notes"),
    path(
        "<uuid:public_id>/",
        NoteViewSet.as_view({"get": "retrieve", "delete": "destroy"}),
        name="note",
    ),
]
