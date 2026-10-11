from django.apps import AppConfig


class ProjectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "project"
    label = "project"  # explicit, like every plugin (CORE_ARCHITECTURE_PLAN.md § 3)

    def ready(self):
        from . import wiring

        wiring.register()
