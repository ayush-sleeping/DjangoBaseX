"""
URL configuration for DjangoBaseX.

  /admin/            Django admin — only when ADMIN_ENABLED (AUTH_BLUEPRINT Ch. 20)
  /api/health/       Public health probe
  /api/schema/       OpenAPI schema (JSON)
  /api/docs/         Swagger UI
  /api/rbac/         Roles and the permission catalog (AUTH_BLUEPRINT § 10.3)
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("api/", include("core.urls")),
    path("api/", include("users.urls")),
    path("api/rbac/", include("rbac.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

# A second authentication and authorization system beside the API's; off unless asked for.
if settings.ADMIN_ENABLED:
    urlpatterns.append(path("admin/", admin.site.urls))
