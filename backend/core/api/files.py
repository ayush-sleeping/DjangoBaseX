"""
/api/files/ — content-sniffed uploads and private serving (API_PLATFORM.md § 18–19).

    POST /api/files/             multipart: purpose, file  -> 201 {id, name, content_type, size}
    GET  /api/files/<id>/             the bytes, if the caller holds the purpose's read permission

There is no public media URL. A download answers 404 (not 403) for a caller who may not read the
purpose, so a guessed id reveals nothing; it is always an attachment, never rendered by the browser.
"""

from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from core import files
from core.api.error_codes import ApiError
from core.api.views import BaseAPIView
from core.models import PrivateFile


class FileUploadSerializer(serializers.Serializer):
    purpose = serializers.CharField(default="general")
    file = serializers.FileField()


class PrivateFileSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    name = serializers.CharField(source="original_name", read_only=True)

    class Meta:
        model = PrivateFile
        fields = ("id", "purpose", "name", "content_type", "size", "created_at")
        read_only_fields = fields


class FileUploadView(BaseAPIView):
    required_permissions = ["core.files.upload"]
    parser_classes = [MultiPartParser]

    @extend_schema(request=FileUploadSerializer, responses={201: PrivateFileSerializer})
    def post(self, request):
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purpose = files.PURPOSES.get(serializer.validated_data["purpose"])
        if purpose is None:
            raise ApiError("validation_error", details={"purpose": ["Unknown purpose."]})
        row = files.save_private(serializer.validated_data["file"], purpose, actor=request.user)
        return Response(PrivateFileSerializer(row).data, status=status.HTTP_201_CREATED)


class FileDownloadView(BaseAPIView):
    required_permissions = []  # the purpose's own read permission is checked below

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request, public_id):
        row = PrivateFile.objects.filter(public_id=public_id).first()
        purpose = files.PURPOSES.get(row.purpose) if row else None
        if row is None or purpose is None or not request.user.has_perm(purpose.read_permission):
            raise ApiError("not_found")
        response = FileResponse(
            files.private_storage().open(row.storage_name),
            as_attachment=True,
            filename=row.original_name,
            content_type=row.content_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response
