from django.contrib import admin

from core.models import Holiday


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    """Manual holiday entry for the business calendar (the other way in is import_holidays)."""

    list_display = ("date", "name", "source")
    list_filter = ("source",)
    search_fields = ("name",)
