"""Token issuance and refresh-token lifecycle helpers."""

import hashlib
import logging

from datetime import UTC, datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, Token

from .models import HashedRefreshToken, RefreshTokenFamily


logger = logging.getLogger(__name__)


class RefreshTokenReuseDetected(TokenError):
    """A previously consumed refresh token was presented again."""


class RotatingRefreshToken(Token):
    """A signed refresh JWT without blacklist persistence."""

    token_type = "refresh"
    lifetime = api_settings.REFRESH_TOKEN_LIFETIME


def hash_refresh_token(raw_token: str) -> str:
    """Return the SHA-256 fingerprint stored by the server."""

    return hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()


def _get_uuid_claim(token, claim_name):
    """Read a UUID claim or reject the malformed token."""

    try:
        return UUID(str(token[claim_name]))
    except (KeyError, TypeError, ValueError) as error:
        raise TokenError(
            f"Refresh token has an invalid {claim_name} claim."
        ) from error


def _create_token_pair_for_family(
    user,
    family,
) -> tuple[dict[str, str], HashedRefreshToken]:
    """Create JWTs and persist only the refresh fingerprint."""

    refresh_token = RotatingRefreshToken.for_user(user)
    refresh_token["family_id"] = str(family.id)

    access_token = AccessToken.for_user(user)
    access_token["family_id"] = str(family.id)

    raw_refresh_token = str(refresh_token)

    expires_at = datetime.fromtimestamp(
        refresh_token["exp"],
        tz=UTC,
    )

    token_record = HashedRefreshToken.objects.create(
        family=family,
        jti=refresh_token["jti"],
        token_hash=hash_refresh_token(
            raw_refresh_token
        ),
        expires_at=expires_at,
    )

    token_pair = {
        "access": str(access_token),
        "refresh": raw_refresh_token,
    }

    return token_pair, token_record


@transaction.atomic
def issue_token_pair(user) -> dict[str, str]:
    """Start a token family and return its first token pair."""

    if not user.is_active:
        raise ValueError(
            "Cannot issue tokens for an inactive user."
        )

    family = RefreshTokenFamily.objects.create(
        user=user,
    )

    token_pair, _ = _create_token_pair_for_family(
        user,
        family,
    )

    return token_pair


def rotate_refresh_token(
    raw_refresh_token: str,
) -> dict[str, str]:
    """Consume one refresh token and issue its replacement."""

    decoded_token = RotatingRefreshToken(
        raw_refresh_token
    )

    family_id = _get_uuid_claim(
        decoded_token,
        "family_id",
    )
    token_jti = _get_uuid_claim(
        decoded_token,
        "jti",
    )
    token_hash = hash_refresh_token(
        raw_refresh_token
    )

    reuse_detected = False
    inactive_user = False
    token_pair = None

    with transaction.atomic():
        try:
            family = (
                RefreshTokenFamily.objects
                .select_for_update()
                .select_related("user")
                .get(id=family_id)
            )
        except RefreshTokenFamily.DoesNotExist as error:
            raise TokenError(
                "Refresh token family is not recognized."
            ) from error

        try:
            token_record = (
                HashedRefreshToken.objects
                .select_for_update()
                .get(
                    family=family,
                    jti=token_jti,
                    token_hash=token_hash,
                )
            )
        except HashedRefreshToken.DoesNotExist as error:
            raise TokenError(
                "Refresh token is not recognized."
            ) from error

        token_user_id = decoded_token.get(
            api_settings.USER_ID_CLAIM
        )

        if str(token_user_id) != str(family.user_id):
            raise TokenError(
                "Refresh token user does not match its family."
            )

        if token_record.used_at is not None:
            detected_at = timezone.now()

            if family.revoked_at is None:
                family.revoked_at = detected_at

            if family.reuse_detected_at is None:
                family.reuse_detected_at = detected_at

            family.save(
                update_fields=[
                    "revoked_at",
                    "reuse_detected_at",
                ]
            )

            family.tokens.filter(
                revoked_at__isnull=True
            ).update(
                revoked_at=detected_at
            )

            reuse_detected = True

        elif (
            family.revoked_at is not None
            or token_record.revoked_at is not None
        ):
            raise TokenError(
                "Refresh token has been revoked."
            )

        elif not family.user.is_active:
            revoked_at = timezone.now()

            family.revoked_at = revoked_at
            family.save(
                update_fields=["revoked_at"]
            )

            family.tokens.filter(
                revoked_at__isnull=True
            ).update(
                revoked_at=revoked_at
            )

            inactive_user = True

        else:
            token_pair, replacement_record = (
                _create_token_pair_for_family(
                    family.user,
                    family,
                )
            )

            token_record.used_at = timezone.now()
            token_record.replaced_by = replacement_record
            token_record.save(
                update_fields=[
                    "used_at",
                    "replaced_by",
                ]
            )

    # These errors are deliberately raised after the transaction commits.
    if reuse_detected:
        logger.warning(
            (
                "Refresh token reuse detected: "
                "user_id=%s family_id=%s jti=%s"
            ),
            family.user_id,
            family.id,
            token_record.jti,
        )

        raise RefreshTokenReuseDetected(
            "Refresh token reuse detected; "
            "the token family has been revoked."
        )

    if inactive_user:
        raise TokenError(
            "Refresh token user is inactive."
        )

    if token_pair is None:
        raise TokenError(
            "Refresh token rotation failed."
        )

    return token_pair