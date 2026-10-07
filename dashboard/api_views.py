from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.generics import (
    ListAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.pagination import PageNumberPagination

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
            if(
                str(refresh_token.get("user_id"))
                != str(request.user.pk)
            ):
             return Response(
                {
                    "detail": (
                        "You cannot revoke this "
                        "refresh token."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )
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

class TransactionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

class TransactionListAPIView(ListAPIView):
    queryset = Transaction.objects.select_related(
        "user"
    )
    serializer_class = TransactionSerializer
    permission_classes = [
        IsAuthenticated,
        TransactionAPIPermission,
    ]
    pagination_class = TransactionPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        currency = self.request.query_params.get(
            "currency"
        )
        if currency:
            queryset = queryset.filter(
                currency=currency
            )
        return queryset
