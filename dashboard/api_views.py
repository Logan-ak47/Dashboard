from django.utils import timezone
from rest_framework.generics import (
    ListAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_204_NO_CONTENT
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import (
    JWTAuthentication,
)
from rest_framework_simplejwt.views import TokenViewBase

from .models import Transaction
from .permissions import (
    CanExportTransactions,
    TransactionAPIPermission,
)
from .serializers import (
    HashedTokenLogoutSerializer,
    HashedTokenObtainPairSerializer,
    HashedTokenRefreshSerializer,
    StepUpPasswordSerializer,
    TransactionSerializer,
)


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


class HashedTokenObtainPairView(TokenViewBase):
    """Authenticate credentials and issue a custom token pair."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = HashedTokenObtainPairSerializer


class HashedTokenRefreshView(TokenViewBase):
    """Rotate a refresh token."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = HashedTokenRefreshSerializer


class HashedTokenLogoutView(APIView):
    """Revoke one authenticated user's refresh-token family."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = HashedTokenLogoutSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(
            raise_exception=True
        )

        return Response(
            status=HTTP_204_NO_CONTENT
        )


class AdminTransactionExportAPIView(APIView):
    """Return a bounded export after admin password re-entry."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [
        IsAuthenticated,
        CanExportTransactions,
    ]
    export_limit = 100

    def post(self, request):
        step_up = StepUpPasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        step_up.is_valid(raise_exception=True)

        queryset = Transaction.objects.select_related(
            "user"
        )
        total_transactions = queryset.count()
        transactions = list(
            queryset[:self.export_limit]
        )

        return Response(
            {
                "generated_at": timezone.now().isoformat(),
                "total_transactions": total_transactions,
                "exported_transactions": len(transactions),
                "truncated": (
                    total_transactions > self.export_limit
                ),
                "results": TransactionSerializer(
                    transactions,
                    many=True,
                ).data,
            }
        )
