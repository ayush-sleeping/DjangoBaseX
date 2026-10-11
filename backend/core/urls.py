from django.urls import path

from .views import HealthView, NavigationView

app_name = "core"

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("me/navigation/", NavigationView.as_view(), name="navigation"),
]
