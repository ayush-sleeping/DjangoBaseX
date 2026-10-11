from django.apps import AppConfig


class NotesConfig(AppConfig):
    name = "djx_notes"
    # Explicit, never derived from the package path: app_label is written into every migration,
    # so renaming the package must not change it (the app-label trap, CORE_ARCHITECTURE_PLAN § 3).
    label = "notes"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Notes"

    def ready(self) -> None:
        from . import wiring

        wiring.register()
