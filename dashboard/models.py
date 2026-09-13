import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
# Create your models here.

class Transaction(models.Model):
    class Currency(models.TextChoices):
       BTC = "BTC", "Bitcoin"
       ETH = "ETH", "Ethereum"
       USDT = "USDT", "Tether"
       USD = "USD", "US Dollar"

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    currency = models.CharField(max_length=10,
                                choices=Currency.choices,)
    status = models.CharField(max_length=20,
                              choices=Status.choices,
                              default=Status.PENDING)
    amount = models.DecimalField(max_digits=20,
                                 decimal_places=8)
    timestamp = models.DateTimeField(default=timezone.now,
                                     db_index=True)
    reference = models.UUIDField(default=uuid.uuid4,
                                 editable=False,
                                 unique=True)

    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.PROTECT,
                             related_name='transactions')

    def __str__(self) -> str:
        return f"{self.reference} - {self.amount} {self.currency}"
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=["status", "timestamp"],
                         name="status_timestamp_idx",
                        ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="amount_positive_check"
            ),
        ]

class DailyMetric(models.Model):
    date=models.DateField()
    currency=models.CharField(max_length=10,
                              choices=Transaction.Currency.choices,
                              )
    transaction_count=models.PositiveIntegerField()
    total_volume=models.DecimalField(max_digits=20,
                                     decimal_places=8)
    class Meta:
        ordering = ['-date', "currency"]
        constraints = [
            models.UniqueConstraint(
                fields=['date', 'currency'],
                name='unique_date_currency'
            ),
        ]
    def __str__(self) -> str:
        return f"{self.date} - {self.currency} - {self.transaction_count}"
    

