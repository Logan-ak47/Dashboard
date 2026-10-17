import hashlib

from datetime import UTC, datetime

from django.db import transaction
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, Token

from dashboard.models import HashedRefreshToken, RefreshTokenFamily

class RotatingRefreshToken():
    """A signed refresh JWT without SimpleJWT blacklist persistence."""

    token_type = "refresh"
    lifetime = api_settings.REFRESH_TOKEN_LIFETIME


def hash_refresh_token(raw_token: str) -> str:
    """Return the deterministic SHA-256 fingerprint stored by the server."""

    return hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()
    
@transaction.atomic
def issue_token_pair(user) -> dict[str, str]:
    """Issue JWTs while persisting only the refresh token's fingerprint."""

    if not user.is_active:
        raise ValueError(
            "Cannot issue tokens for an inactive user."
        )

    family = RefreshTokenFamily.objects.create(
        user=user,
    )

    refresh_token = RotatingRefreshToken.for_user(user)
    refresh_token["family_id"] = str(family.id)

    access_token = AccessToken.for_user(user)
    access_token["family_id"] = str(family.id)

    raw_refresh_token = str(refresh_token)

    expires_at = datetime.fromtimestamp(
        refresh_token["exp"],
        tz=UTC,
    )

    HashedRefreshToken.objects.create(
        family=family,
        jti=refresh_token["jti"],
        token_hash=hash_refresh_token(
            raw_refresh_token
        ),
        expires_at=expires_at,
    )

    return {
        "access": str(access_token),
        "refresh": raw_refresh_token,
    }