
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from dashboard.models import DailyMetric, Transaction

class Command(BaseCommand):
    help = "Generate realistic demo data for OpsBoard."
    

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=5000,
            help="Number of transactions to create",
            
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing opsboard-demo transactions before generating.",
        )

    @db_transaction.atomic
    def handle(self, *args, **options) -> None:
        count = options["count"]
        if count < 1 or count > 10_000:
            raise CommandError("Count must be between 1 and 10,000")
        User = get_user_model()
        demo_user, created = User.objects.get_or_create(
            username="opsboard-demo",
          defaults={
                "is_active": True,
          },
        )
        if options["clear"]:
            deleted_count, _ = Transaction.objects.filter(
                user=demo_user
            ).delete()
            self.stdout.write(f"Deleted {deleted_count} transactions for demo user: {demo_user.username}")
        self.stdout.write(f"Preparing to generate {count} transactions for demo user: {demo_user.username}")
        if created:
            demo_user.set_unusable_password()
            demo_user.save(update_fields=["password"])
        currencies = list(Transaction.Currency.values)
        statuses = [Transaction.Status.COMPLETED, Transaction.Status.PENDING, Transaction.Status.FAILED]

        status_weights = [85, 10, 5]
        amount_ranges = {
            Transaction.Currency.BTC: (10_000, 200_000_000),
            Transaction.Currency.ETH: (100_000, 5_000_000_000),
            Transaction.Currency.USDT: (500_000_000, 500_000_000_000),
            Transaction.Currency.USD: (500_000_000, 500_000_000_000),

        }

        decimal_scale = Decimal("100000000")
        now = timezone.now()
        transactions = []

        for _ in range(count):
            currency = random.choice(currencies)
            minimum, maximum = amount_ranges[currency]
            amount = Decimal(
                random.randint(minimum, maximum)) / decimal_scale
            status = random.choices(statuses,
                                  weights=status_weights,
                                  k=1)[0]
            timestamp = now - timedelta(
                days=random.randint(0, 89),
                seconds=random.randint(0, 86399),
            )

            transactions.append(
                Transaction(
                    user=demo_user,
                    amount=amount,
                    currency=currency,
                    status=status,
                    timestamp=timestamp,
                )
            )

        Transaction.objects.bulk_create(
            transactions,
            batch_size=1000,
        )

        rollups=(
            Transaction.objects
            .filter(status=Transaction.Status.COMPLETED)
            .annotate(metric_date=TruncDate("timestamp"))
            .values("metric_date","currency")
            .annotate(
                transaction_count=Count("id"),
                total_volume=Sum("amount"),
            )
            .order_by()
        )

        DailyMetric.objects.all().delete()

        daily_metrics=[
            DailyMetric(
                date=row["metric_date"],
                currency=row["currency"],
                transaction_count=row["transaction_count"],
                total_volume=row["total_volume"],
            )
            for row in rollups
        ]

        DailyMetric.objects.bulk_create(
            daily_metrics,
            batch_size=500,
        )
        
        
        self.stdout.write(
           self.style.SUCCESS(f"created {len(transactions)} and " 
                              f"rebuilt {len(daily_metrics)} daily metrics"
                             )
        )

    
