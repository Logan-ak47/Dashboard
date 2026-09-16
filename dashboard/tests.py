from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from .models import DailyMetric, Transaction





class HomeViewTests(TestCase):
    def test_home_page_renders(self) -> None:
        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OpsBoard")
        self.assertTemplateUsed(response, "dashboard/home.html")

class AdminPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        viewer_group = Group.objects.create(name="Viewer")
        view_transaction = Permission.objects.get(
            codename="view_transaction",
            content_type__app_label="dashboard",
        )
        viewer_group.permissions.add(view_transaction)

        cls.viewer = get_user_model().objects.create_user(
        username="viewer-test",
        password="testpassword",
        is_staff=True,
        )
        cls.viewer.groups.add(viewer_group)

    def test_viewer_can_view_transaction_list(self) -> None:
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("admin:dashboard_transaction_changelist")
        )
        self.assertEqual(response.status_code, 200)

    def test_viewer_cannot_add_transaction(self) -> None:
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("admin:dashboard_transaction_add")
        )
        self.assertEqual(response.status_code, 403)

class SeedDataCommandTests(TestCase):
    def test_clear_replaces_existing_demo_transactions(self) -> None:
        output = StringIO()

        call_command(
            "seed_data",
            count=3,
            stdout=output,
        )
        call_command(
            "seed_data",
            count=2,
            clear=True,
            stdout=output,
        )

        demo_transaction_count = Transaction.objects.filter(
            user__username="opsboard-demo"
        ).count()

        self.assertEqual(demo_transaction_count, 2)

    def test_daily_metrics_match_completed_transactions(self) -> None:
        output = StringIO()
        call_command(
            "seed_data",
            count=25,
            clear=True,
            stdout=output,
        )
        completed_transactions = Transaction.objects.filter(
            status=Transaction.Status.COMPLETED
        )

        completed_count = completed_transactions.count()
        completed_volume = (
            completed_transactions.aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        metric_totals = DailyMetric.objects.aggregate(
            count=Sum("transaction_count"),
            volume=Sum("total_volume"),
        )

        metric_count = metric_totals["count"] or 0
        metric_volume = metric_totals["volume"] or Decimal("0")

        self.assertEqual(metric_count, completed_count)
        self.assertEqual(
              metric_volume.quantize(Decimal("0.00000001")),
              completed_volume.quantize(Decimal("0.00000001")),
        )
