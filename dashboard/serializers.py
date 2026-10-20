from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.exceptions import (
    InvalidToken,
    TokenError,
)
from rest_framework_simplejwt.serializers import (
    TokenObtainSerializer,
)

from .models import Transaction
from .token_service import (
    RefreshTokenOwnershipError,
    issue_token_pair,
    revoke_refresh_token_family,
    rotate_refresh_token,
)


class TransactionSerializer(serializers.ModelSerializer):
    user = serializers.CharField(
        source="user.username",
        read_only=True,
    )

    class Meta:
        model = Transaction
        fields = (
            "reference",
            "user",
            "amount",
            "currency",
            "status",
            "timestamp",
        )
        read_only_fields = (
            "reference",
            "user",
            "amount",
            "currency",
            "timestamp",
        )


class HashedTokenObtainPairSerializer(
    TokenObtainSerializer
):
    """Authenticate credentials and start a token family."""

    def validate(self, attrs):
        super().validate(attrs)

        return issue_token_pair(self.user)


class HashedTokenRefreshSerializer(
    serializers.Serializer
):
    """Rotate a refresh token or reject its reuse."""

    refresh = serializers.CharField(
        trim_whitespace=False,
    )
    access = serializers.CharField(
        read_only=True,
    )

    def validate(self, attrs):
        try:
            return rotate_refresh_token(
                attrs["refresh"]
            )
        except TokenError as error:
            raise InvalidToken(
                str(error)
            ) from error


class HashedTokenLogoutSerializer(
    serializers.Serializer
):
    """Revoke the submitted refresh-token family."""

    refresh = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        request = self.context["request"]

        try:
            revoke_refresh_token_family(
                attrs["refresh"],
                request.user,
            )
        except RefreshTokenOwnershipError as error:
            raise PermissionDenied(
                str(error)
            ) from error
        except TokenError as error:
            raise InvalidToken(
                str(error)
            ) from error

        return {}


class StepUpPasswordSerializer(serializers.Serializer):
    """Re-authenticate the JWT user for one sensitive action."""

    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    def validate(self, attrs):
        user = self.context["request"].user

        if not user.check_password(attrs["password"]):
            raise PermissionDenied(
                "Step-up authentication failed."
            )

        # Do not carry the plaintext password beyond validation.
        return {}
