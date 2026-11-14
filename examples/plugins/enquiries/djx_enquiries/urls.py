from django.urls import path

from .views import EnquiryViewSet

app_name = "enquiries"

# Mounted at /api/enquiries/ through registry.api_routes (wiring.py).
urlpatterns = [
    path("", EnquiryViewSet.as_view({"get": "list", "post": "create"}), name="enquiries"),
    path(
        "<uuid:public_id>/",
        EnquiryViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="enquiry",
    ),
    path(
        "<uuid:public_id>/transition/",
        EnquiryViewSet.as_view({"post": "move"}),
        name="enquiry-transition",
    ),
]
