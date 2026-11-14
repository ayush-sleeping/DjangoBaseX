from django.apps import AppConfig


class EnquiriesConfig(AppConfig):
    name = "djx_enquiries"
    # Explicit, never derived from the package path: app_label is written into every migration.
    label = "enquiries"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Enquiries"

    def ready(self) -> None:
        from . import wiring

        wiring.register()
