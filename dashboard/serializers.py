from rest_framework import serializers

from .models import Transaction


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