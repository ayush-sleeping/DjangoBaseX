from django.utils.cache import patch_cache_control


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
        if request.path.startswith("/api/auth/") or (user is not None and user.is_authenticated):
            patch_cache_control(response, no_store=True, private=True)
        return response
