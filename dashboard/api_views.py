from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.generics import RetrieveUpdateAPIView

from .models import Transaction
from .permissions import TransactionAPIPermission
from .serializers import TransactionSerializer


class JWTLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_value = request.data.get("refresh")

        if not refresh_value:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh_token = RefreshToken(refresh_value)
            refresh_token.blacklist()
        except TokenError:
            return Response(
                {"detail": "Refresh token is invalid or expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransactionDetailAPIView(RetrieveUpdateAPIView):
    queryset = Transaction.objects.select_related("user")
    serializer_class = TransactionSerializer
    permission_classes = [
        IsAuthenticated,
        TransactionAPIPermission,
    ]
    lookup_field = "reference"
    http_method_names = [
        "get",
        "patch",
        "head",
        "options",
    ]
