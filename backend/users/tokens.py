"""
Access and refresh JWTs, and the session rows behind them (ADR-0009, AUTH_BLUEPRINT § 6.1–6.4).

- The access token (short) carries `sub` (user public_id) and `sid` (session public_id).
- The refresh token carries a random `jti`. Only its SHA-256 is stored; the plaintext lives in the
  cookie alone. Each refresh rotates it: the old row is revoked as `rotated`, a successor is created
  in the same family, and presenting a rotated token again revokes the whole family.
- A successor's jti is derived from its parent's (HMAC). That is what lets the two-tab grace window
  (A23) hand a racing tab the *same* successor instead of minting a third token, without storing
  any plaintext.
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from core.http import client_ip

from .models import UserSession

ALGORITHM = "HS256"
ACCESS = "access"
REFRESH = "refresh"


class TokenError(Exception):
    """A token that must not authenticate. The caller answers 401; the message is for the log."""


class ReuseDetected(TokenError):
    """A rotated refresh token came back outside the grace window. Its family is already revoked."""


@dataclass(frozen=True)
class IssuedTokens:
    access: str
    refresh: str
    csrf: str
    session: UserSession


# --- Primitives -------------------------------------------------------------------------------


def hash_jti(raw_jti: str) -> str:
    return hashlib.sha256(raw_jti.encode()).hexdigest()


def _hmac(message: str) -> bytes:
    return hmac.new(settings.JWT_SIGNING_KEY.encode(), message.encode(), hashlib.sha256).digest()


def csrf_token_for(sid: str) -> str:
    """Session-bound CSRF value (A22): a planted cookie cannot match the victim's session."""
    return base64.urlsafe_b64encode(_hmac(f"csrf:{sid}")).decode().rstrip("=")


def csrf_matches(sid: str, presented: str | None) -> bool:
    return bool(presented) and hmac.compare_digest(csrf_token_for(sid), presented)


def _successor_jti(raw_jti: str) -> str:
    return base64.urlsafe_b64encode(_hmac(f"rotate:{raw_jti}")).decode().rstrip("=")


def decode(token: str, expected_type: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub", "sid", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(f"invalid {expected_type} token: {exc}") from exc
    if claims["typ"] != expected_type:
        raise TokenError(f"expected a {expected_type} token, got {claims['typ']!r}")
    return claims


def _mint(session: UserSession, raw_jti: str, now: datetime) -> IssuedTokens:
    base = {"sub": str(session.user.public_id), "sid": str(session.public_id), "iat": now}
    access_exp = now + timedelta(seconds=settings.ACCESS_TOKEN_LIFETIME)
    access = jwt.encode(
        {**base, "typ": ACCESS, "exp": access_exp}, settings.JWT_SIGNING_KEY, ALGORITHM
    )
    refresh = jwt.encode(
        {**base, "typ": REFRESH, "jti": raw_jti, "exp": session.expires_at},
        settings.JWT_SIGNING_KEY,
        ALGORITHM,
    )
    return IssuedTokens(access, refresh, csrf_token_for(str(session.public_id)), session)


# --- Session liveness (§ 6.4) -------------------------------------------------------------------


def _live_key(sid: str) -> str:
    return f"auth:session-live:{sid}"


def session_is_live(sid: str, user) -> bool:
    """Is the session behind an access token still usable? Cached for SESSION_LIVENESS_CACHE_TTL."""
    state = cache.get(_live_key(sid))
    if state is None:
        row = (
            UserSession.objects.filter(public_id=sid, user=user)
            .values("revoked_at", "expires_at", "issued_at")
            .first()
        )
        if row is None or row["revoked_at"] is not None:
            return False
        state = {"expires_at": row["expires_at"], "issued_at": row["issued_at"]}
        if settings.SESSION_LIVENESS_CACHE_TTL > 0:
            cache.set(_live_key(sid), state, settings.SESSION_LIVENESS_CACHE_TTL)
    if state["expires_at"] <= timezone.now():
        return False
    changed = user.password_changed_at
    return changed is None or state["issued_at"] >= changed


def _forget(sids) -> None:
    # Revocation deletes the cached answer, so on a shared cache it takes effect at once rather
    # than after the TTL. The TTL bounds only a cache that missed the delete.
    cache.delete_many([_live_key(str(sid)) for sid in sids])


# --- Lifecycle --------------------------------------------------------------------------------


def issue_pair(user, request) -> IssuedTokens:
    """A new login: a new session row in a new family."""
    now = timezone.now()
    raw_jti = secrets.token_urlsafe(32)
    session = UserSession.objects.create(
        user=user,
        jti=hash_jti(raw_jti),
        family_id=uuid.uuid4(),
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.REFRESH_TOKEN_LIFETIME),
        last_seen_at=now,
        ip=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )
    return _mint(session, raw_jti, now)


def rotate(refresh_token: str, request) -> IssuedTokens:
    """
    Exchange a refresh token for a new pair (§ 6.3). Raises TokenError for anything that must
    answer 401. A reuse outside the grace window revokes the whole family *before* raising, so
    the revocation commits even though the request fails.
    """
    claims = decode(refresh_token, REFRESH)
    raw_jti = claims.get("jti")
    if not raw_jti:
        raise TokenError("refresh token has no jti")

    failure = None
    issued = None
    with transaction.atomic():
        session = (
            UserSession.objects.select_for_update()
            .select_related("user")
            .filter(jti=hash_jti(raw_jti))
            .first()
        )
        now = timezone.now()
        if session is None:
            failure = TokenError("unknown refresh token")
        elif session.revoked_at is not None:
            issued = _grace_reissue(session, raw_jti, now)
            if issued is None:
                revoke_family(session.family_id, UserSession.RevokedReason.REUSE_DETECTED)
                failure = ReuseDetected("refresh token reused; family revoked")
        elif (
            session.expires_at <= now
            or session.last_seen_at + timedelta(seconds=settings.REFRESH_IDLE_LIFETIME) <= now
        ):
            _revoke_rows([session], UserSession.RevokedReason.EXPIRED, now)
            failure = TokenError("session expired")
        elif not session.user.is_active:
            failure = TokenError("user is inactive")
        elif (
            session.user.password_changed_at
            and session.issued_at < session.user.password_changed_at
        ):
            failure = TokenError("session predates the last password change")
        else:
            issued = _rotate_row(session, raw_jti, request, now)

    if failure:
        raise failure
    return issued


def _rotate_row(session: UserSession, raw_jti: str, request, now: datetime) -> IssuedTokens:
    new_raw = _successor_jti(raw_jti)
    successor = UserSession.objects.create(
        user=session.user,
        jti=hash_jti(new_raw),
        family_id=session.family_id,
        parent_jti=session.jti,
        issued_at=now,
        expires_at=session.expires_at,  # the absolute cap survives rotation
        last_seen_at=now,
        password_confirmed_at=session.password_confirmed_at,
        ip=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
        device_label=session.device_label,
    )
    session.revoked_at = now
    session.revoked_reason = UserSession.RevokedReason.ROTATED
    session.replaced_by_jti = successor.jti
    session.save(update_fields=["revoked_at", "revoked_reason", "replaced_by_jti"])
    _forget([session.public_id])
    return _mint(successor, new_raw, now)


def _grace_reissue(session: UserSession, raw_jti: str, now: datetime) -> IssuedTokens | None:
    """A23: a token rotated moments ago, whose successor is still live, is a race, not theft."""
    if session.revoked_reason != UserSession.RevokedReason.ROTATED:
        return None
    if now - session.revoked_at > timedelta(seconds=settings.REFRESH_ROTATION_GRACE):
        return None
    successor_raw = _successor_jti(raw_jti)
    if hash_jti(successor_raw) != session.replaced_by_jti:
        return None
    successor = (
        UserSession.objects.select_related("user").filter(jti=session.replaced_by_jti).first()
    )
    if successor is None or not successor.is_live or not successor.user.is_active:
        return None
    return _mint(successor, successor_raw, now)


def _revoke_rows(sessions, reason: str, now: datetime | None = None) -> int:
    ids = [s.pk for s in sessions]
    count = UserSession.objects.filter(pk__in=ids, revoked_at__isnull=True).update(
        revoked_at=now or timezone.now(), revoked_reason=reason
    )
    _forget([s.public_id for s in sessions])
    return count


def revoke(session: UserSession, reason: str) -> int:
    return _revoke_rows([session], reason)


def revoke_family(family_id, reason: str) -> int:
    return _revoke_rows(list(UserSession.objects.filter(family_id=family_id)), reason)


def revoke_all_for_user(user, reason: str, keep_sid: str | None = None) -> int:
    sessions = UserSession.objects.for_user(user).filter(revoked_at__isnull=True)
    if keep_sid:
        sessions = sessions.exclude(public_id=keep_sid)
    return _revoke_rows(list(sessions), reason)
