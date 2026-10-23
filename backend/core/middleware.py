from django.conf import settings
from django.utils.cache import patch_cache_control

from core.settings_service import begin_snapshot, end_snapshot


class NoStoreForAuthenticatedMiddleware:
    """
    `Cache-Control: no-store, private` on every response to an authenticated request, and on every
    /api/auth/ response (they set or carry credentials). A proxy, CDN or back-forward cache holding
    one user's /me and serving it to the next person is a real leak (AUTH_BLUEPRINT § 6.4).
    DRF sets request.user on the underlying request, so this sees API authentication too.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if request.path.startswith(f"/{settings.API_PREFIX}/auth/") or (
            user is not None and user.is_authenticated
        ):
            patch_cache_control(response, no_store=True, private=True)
        return response


class SettingsSnapshotMiddleware:
    """
    One consistent value per setting for the whole request (CONFIGURATION.md § 9.7): a request that
    reads a key twice never sees an admin's save land halfway through it. The snapshot ends with
    the request, so it is never a per-process cache. A job runner needs the same per task (a Celery
    task_prerun/task_postrun pair, when Celery arrives).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = begin_snapshot()
        try:
            return self.get_response(request)
        finally:
            end_snapshot(token)
