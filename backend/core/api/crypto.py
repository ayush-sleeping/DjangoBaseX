"""
GET /api/system/crypto/ (JOBS § 25): key fingerprints (never keys) and rows per key for each
registered encrypted field — the system-health page's view of "is rotation finished?".
"""

from django.apps import apps
from rest_framework.response import Response

from core import crypto
from core.api.views import BaseAPIView
from core.registry import registry


class CryptoStatusView(BaseAPIView):
    required_permissions = ["settings.crypto.view"]

    def get(self, request):
        try:
            fingerprints = crypto.key_fingerprints()
        except crypto.CryptoNotConfigured:
            return Response({"configured": False, "keys": [], "fields": []})
        fields = []
        for spec in registry.encrypted_fields.fields():
            model = apps.get_model(spec.model)
            counts = dict.fromkeys([*fingerprints, crypto.UNREADABLE], 0)
            for row in model.objects.exclude(**{spec.field: ""}).iterator(chunk_size=500):
                owner = crypto.fingerprint_of(getattr(row, spec.field), purpose=spec.purpose)
                counts[owner or crypto.UNREADABLE] += 1
            fields.append(
                {
                    "model": spec.model,
                    "field": spec.field,
                    "purpose": spec.purpose,
                    "rows_per_key": counts,
                }
            )
        return Response(
            {
                "configured": True,
                "keys": [
                    {"fingerprint": fp, "newest": fp == fingerprints[0]} for fp in fingerprints
                ],
                "fields": fields,
            }
        )
