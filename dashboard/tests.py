from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db.models import Sum
from django.test import RequestFactory,TestCase
from django.urls import reverse
from .models import DailyMetric, Transaction
from django.utils import timezone
from urllib.parse import quote
from django.urls import reverse


from .views import TransactionListView


class HomeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls)->None:
        cls.user = get_user_model().objects.create_user(
            username="dashboard-viewer",
            password="test-password",
        )

        Transaction.objects.create(
            user=cls.user,
            amount=Decimal("10.00000000"),
            currency=Transaction.Currency.USD,
            status=Transaction.Status.COMPLETED,
        )
        Transaction.objects.create(
            user=cls.user,
            amount=Decimal("5.00000000"),
            currency=Transaction.Currency.USD,
            status=Transaction.Status.FAILED,
        )
        DailyMetric.objects.create(
            date=timezone.localdate(),
            currency=Transaction.Currency.USD,
            transaction_count=1,
            total_volume=Decimal("10.00000000"),
        )
    def test_anonymous_user_is_redirected_to_login(self) -> None:
            response = self.client.get(
            reverse("dashboard:home")
        )
            self.assertEqual(response.status_code,302)

    def test_home_page_renders_summary(self)->None:
        self.client.force_login(self.user)
        response=self.client.get(
            reverse("dashboard:home")
        )
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(
            response,
            "dashboard/home.html"
        )
        self.assertEqual(
            response.context["summary"]["total_transactions"],
            2
        )
        self.assertEqual(
            response.context["summary"]["completed_transactions"],
            1
        )
        self.assertEqual(
            response.context["summary"]["completed_volume"],
            Decimal("10.00000000"),
        )

    def test_daily_volume_endpoint_returns_aligned_datasets(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(
        reverse("dashboard:daily_volume_chart")
        )
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
        payload["labels"],
        [timezone.localdate().isoformat()],
        )
        self.assertEqual(len(payload["datasets"]), 4)
        datasets_by_currency = {
            dataset["label"]: dataset["data"]
            for dataset in payload["datasets"]
            }
        self.assertEqual(
                        datasets_by_currency[Transaction.Currency.USD],
             [10.0],
            )
        self.assertEqual(
            datasets_by_currency[Transaction.Currency.BTC],
            [0],
            )



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

class TransactionListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls)->None:
        cls.user=get_user_model().objects.create_user(
            username="list-viewer",
            password="test-password"
        )

        Transaction.objects.bulk_create(
            [
                Transaction(
                    user=cls.user,
                    amount=Decimal("10.00000000"),
                    currency=Transaction.Currency.USD,
                    status=(
                        Transaction.Status.COMPLETED
                        if index<30
                        else Transaction.Status.FAILED
                    ),
                )
                for index in range(55)
            ]
        )

    def test_anonymous_user_is_redirected_to_login(self)->None:
        url=reverse("dashboard:transaction_list")
        response=self.client.get(url)
        expected_url=(
             f"{reverse('login')}?next="
             f"{quote(reverse('dashboard:transaction_list'), safe='')}"
        )

        self.assertRedirects(
            response,
            expected_url,
            fetch_redirect_response=False,
        )

    def test_transaction_are_paginated_by_fifty(self)->None:
        self.client.force_login(self.user)
        url=reverse("dashboard:transaction_list")

        first_page_response = self.client.get(url)
        second_page_response=self.client.get(
            url,
            {"page":2},
        )
        self.assertEqual(
        len(first_page_response.context["transactions"]),
        50,
        )
        self.assertEqual(
        len(second_page_response.context["transactions"]),
        5,
        )
        self.assertEqual(
        second_page_response.context["page_obj"].number,
        2,
        )

    def test_status_filter_returns_only_selected_status(self) -> None:
     self.client.force_login(self.user)
     url = reverse("dashboard:transaction_list")

     response = self.client.get(
        url,
        {"status": Transaction.Status.FAILED},
     )

     transactions = response.context["transactions"]

     self.assertEqual(len(transactions), 25)
     self.assertTrue(
        all(
            transaction.status == Transaction.Status.FAILED
            for transaction in transactions
        )
     )
     self.assertEqual(
        response.context["selected_status"],
        Transaction.Status.FAILED,
     )

    def test_pagination_links_preserve_search_filter(self) -> None:
        self.client.force_login(self.user)
        url = reverse("dashboard:transaction_list")

        response = self.client.get(
         url,
        {"search": "list-viewer"},
        )

        self.assertEqual(
        response.context["query_string"],
        "search=list-viewer",
        )
        self.assertContains(
        response,
        'href="?search=list-viewer&amp;page=2"',
        )

    def test_transaction_users_are_loaded_in_one_query(self) -> None:
        request = RequestFactory().get(
        reverse("dashboard:transaction_list")
        )
        request.user = self.user

        view = TransactionListView()
        view.setup(request)

        with self.assertNumQueries(1):
            transactions = list(
            view.get_queryset()[:50]
            )
            usernames = [
            transaction.user.username
            for transaction in transactions
            ]
class AuthenticationFlowTests(TestCase):
    def setUp(self):
        self.password = "safe-test-password"
        self.user = get_user_model().objects.create_user(
            username="viewer",
            password=self.password,
        )

    def test_login_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("dashboard:home"),
        )

    def test_logout_redirects_to_login(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("logout"))

        self.assertRedirects(
            response,
            reverse("login"),
        )