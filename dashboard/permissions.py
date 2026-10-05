
from rest_framework.permissions import (
    BasePermission,
    SAFE_METHODS,
)


class TransactionAPIPermission(BasePermission):
    message = (
        "You do not have permission to perform "
        "this transaction operation."
    )

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user.has_perm(
                "dashboard.view_transaction"
            )

        return request.user.has_perm(
            "dashboard.change_transaction"
        )