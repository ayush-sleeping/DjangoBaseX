"""
/api/notifications/ (NOTIFICATIONS_AND_ALERTING.md §§ 1, 4, 5, 8). Thin: parse, authorize, delegate.

Own data, any signed-in user (a row of another user is a 404, never a 403):
    GET  /api/notifications/                    ?unread=true&level=action
    GET  /api/notifications/summary/            the polled bell: {unread, open_actions, latest_id}
    POST /api/notifications/<uuid>/read/
    POST /api/notifications/<uuid>/resolve/     {"note": ""}  closes everyone's prompt
    POST /api/notifications/read-all/           {"up_to_id": n}
    GET/PATCH /api/me/notification-preferences/
Admin (core.notifications.view / .manage):
    GET/POST /api/notifications/routes/ ; PATCH/DELETE .../routes/<id>/ ; POST .../routes/<id>/test/
    GET/PATCH /api/notifications/matrix/ ; GET /api/notifications/purposes/
    POST /api/notifications/purposes/<code>/test/ ; GET /api/notifications/deliveries/
"""

from rest_framework import status
from rest_framework.response import Response

from core.api.errors import error_response, from_exception
from core.api.viewsets import BaseViewSet
from core.models import Notification, NotificationRoute
from core.notifications import inapp, service
from core.registry import registry


def _own(user):
    return Notification.objects.filter(recipient=user)


def _row(n: Notification) -> dict:
    return {
        "id": str(n.public_id),
        "numeric_id": n.pk,
        "purpose": n.purpose_code,
        "level": n.level,
        "title": n.title,
        "body": n.body,
        "url": n.url,
        "count": n.count,
        "read": n.read_at is not None,
        "resolved": n.resolved_at is not None,
        "updated_at": n.updated_at,
    }


def _route(r: NotificationRoute) -> dict:
    return {
        "id": r.pk,
        "purpose": r.purpose_code,
        "channel": r.channel,
        "target": r.target,
        "is_active": r.is_active,
    }


class NotificationViewSet(BaseViewSet):
    """The bell. Every action is scoped to request.user in the queryset."""

    required_permissions = {
        a: [] for a in ("list", "summary", "mark_read", "read_all", "resolve_item")
    }

    def get_queryset(self):
        return _own(self.request.user)

    def list(self, request):
        rows = self.get_queryset()
        if request.query_params.get("unread") == "true":
            rows = rows.filter(read_at__isnull=True)
        if level := request.query_params.get("level"):
            rows = rows.filter(level=level)
        return Response([_row(n) for n in rows[: self.max_page_size]])

    def summary(self, request):
        return Response(inapp.summary(request.user))

    def mark_read(self, request, public_id=None):
        row = self.get_object()
        inapp.mark_read(request.user, row)
        return Response(_row(self.get_queryset().get(pk=row.pk)))

    def resolve_item(self, request, public_id=None):
        row = self.get_object()
        inapp.resolve(row.object_ref, by=request.user, note=str(request.data.get("note", "")))
        if not row.object_ref and row.resolved_at is None:  # no subject to share: close this row
            _own(request.user).filter(pk=row.pk).update(resolved_by=request.user)
            inapp.resolve_one(row)
        return Response(_row(self.get_queryset().get(pk=row.pk)))

    def read_all(self, request):
        up_to = request.data.get("up_to_id")
        if not isinstance(up_to, int) or isinstance(up_to, bool):
            return error_response("invalid", "Send up_to_id.", status.HTTP_400_BAD_REQUEST)
        return Response({"updated": inapp.mark_all_read(request.user, up_to)})


class NotificationPreferenceViewSet(BaseViewSet):
    required_permissions = {"retrieve": [], "partial_update": []}

    def retrieve(self, request):
        return Response(service.preferences_for(request.user))

    def partial_update(self, request):
        changes = request.data if isinstance(request.data, list) else request.data.get("changes")
        try:
            service.set_preferences(user=request.user, changes=changes or [])
        except service.Locked as exc:
            return from_exception(exc, status.HTTP_409_CONFLICT)
        except service.NotificationAdminError as exc:
            return error_response("invalid", str(exc), status.HTTP_400_BAD_REQUEST)
        return Response(service.preferences_for(request.user))


class NotificationAdminViewSet(BaseViewSet):
    required_permissions = {
        "routes": ["core.notifications.view"],
        "matrix": ["core.notifications.view"],
        "purposes": ["core.notifications.view"],
        "deliveries": ["core.notifications.view"],
        "route_create": ["core.notifications.manage"],
        "route_update": ["core.notifications.manage"],
        "route_delete": ["core.notifications.manage"],
        "route_test": ["core.notifications.manage"],
        "matrix_update": ["core.notifications.manage"],
        "purpose_test": ["core.notifications.manage"],
    }
    lookup_field = "pk"

    def routes(self, request):
        return Response([_route(r) for r in NotificationRoute.objects.all()])

    def _save(self, request, route=None):
        data = request.data
        try:
            saved = service.save_route(
                actor=request.user,
                route=route,
                purpose_code=data.get("purpose", route.purpose_code if route else ""),
                channel=data.get("channel", route.channel if route else ""),
                target=data.get("target", route.target if route else {}),
                is_active=bool(data.get("is_active", route.is_active if route else True)),
            )
        except service.InvalidRoute as exc:
            return error_response(
                "invalid", "Check the fields.", status.HTTP_400_BAD_REQUEST,
                details={exc.field: [str(exc)]},
            )  # fmt: skip
        return Response(_route(saved), status=status.HTTP_200_OK if route else 201)

    def route_create(self, request):
        return self._save(request)

    def route_update(self, request, pk=None):
        route = NotificationRoute.objects.filter(pk=pk).first()
        if route is None:
            return error_response("not_found", "No such route.", status.HTTP_404_NOT_FOUND)
        return self._save(request, route)

    def route_delete(self, request, pk=None):
        route = NotificationRoute.objects.filter(pk=pk).first()
        if route is None:
            return error_response("not_found", "No such route.", status.HTTP_404_NOT_FOUND)
        service.delete_route(actor=request.user, route=route)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def route_test(self, request, pk=None):
        route = NotificationRoute.objects.filter(pk=pk).first()
        if route is None:
            return error_response("not_found", "No such route.", status.HTTP_404_NOT_FOUND)
        results = service.send_test(
            actor=request.user, purpose_code=route.purpose_code, route=route
        )
        return Response({"results": results}, status=status.HTTP_202_ACCEPTED)

    def matrix(self, request):
        return Response(service.matrix())

    def matrix_update(self, request):
        changes = request.data if isinstance(request.data, list) else request.data.get("changes")
        try:
            service.set_cells(actor=request.user, changes=changes or [])
        except service.Locked as exc:
            return from_exception(exc, status.HTTP_409_CONFLICT)
        except service.NotificationAdminError as exc:
            return error_response("invalid", str(exc), status.HTTP_400_BAD_REQUEST)
        return Response(service.matrix())

    def purposes(self, request):
        return Response(
            [
                {
                    "code": p.code,
                    "label": p.label,
                    "module": p.owner_module,
                    "audience": list(p.audience),
                    "default_channels": list(p.default_channels),
                    "mandatory": p.mandatory,
                    "carries_token": p.carries_token,
                }
                for p in registry.notification_purposes.purposes()
            ]
        )

    def purpose_test(self, request, code=None):
        try:
            results = service.send_test(
                actor=request.user, purpose_code=code, channel=request.data.get("channel")
            )
        except service.InvalidRoute:
            return error_response("not_found", "No such purpose.", status.HTTP_404_NOT_FOUND)
        return Response({"results": results}, status=status.HTTP_202_ACCEPTED)

    def deliveries(self, request):
        return Response(
            [
                {
                    "id": d.pk,
                    "purpose": d.purpose_code,
                    "channel": d.channel,
                    "status": d.status,
                    "skip_reason": d.skip_reason,
                    "error_code": d.error_code,
                    "is_test": d.is_test,
                    "created_at": d.created_at,
                }
                for d in service.deliveries()
            ]
        )
