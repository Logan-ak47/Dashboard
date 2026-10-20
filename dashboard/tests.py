import os
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from urllib.parse import quote
from datetime import timedelta
import hashlib
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db.models import Sum
from django.test import RequestFactory,TestCase
from django.urls import reverse

from dashboard.token_service import RotatingRefreshToken, issue_token_pair
from .models import DailyMetric, Transaction,HashedRefreshToken, RefreshTokenFamily
from django.utils import timezone
from django.utils.html import escape
from django.core.management.base import CommandError
from django.db import models

from .views import TransactionListView

from rest_framework.test import (
    APIClient,
    APITestCase,
)

from rest_framework import status
from rest_framework_simplejwt.tokens import (
    AccessToken,
    RefreshToken,
)

from .models import HashedRefreshToken, RefreshTokenFamily
from .token_service import (
    RotatingRefreshToken,
    hash_refresh_token,
    issue_token_pair,
    RefreshTokenReuseDetected,
    hash_refresh_token,
    rotate_refresh_token,
)
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
)


from rest_framework_simplejwt.exceptions import TokenError

from .token_service import (
    RefreshTokenOwnershipError,
    revoke_refresh_token_family,
)





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
    def test_daily_volume_endpoint_rejects_anonymous_user(
            self,
        ) -> None:
            response = self.client.get(
                reverse("dashboard:daily_volume_chart")
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_401_UNAUTHORIZED,
            )
    def test_daily_volume_endpoint_accepts_jwt(
            self,
        ) -> None:
        access_token = RefreshToken.for_user(
            self.user
        ).access_token

        response = self.client.get(
            reverse("dashboard:daily_volume_chart"),
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIn("labels", response.json())
        self.assertIn("datasets", response.json())


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

    def test_transaction_username_is_html_escaped(self):
        malicious_username = (
            '<script>alert("xss")</script>'
        )

        malicious_user = (
            get_user_model().objects.create_user(
                username=malicious_username,
                password="test-password",
            )
        )

        Transaction.objects.create(
            user=malicious_user,
            amount=Decimal("1.00000000"),
            currency=Transaction.Currency.USD,
            status=Transaction.Status.COMPLETED,
        )

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("dashboard:transaction_list")
        )

        self.assertContains(
            response,
            escape(malicious_username),
        )
        self.assertNotContains(
            response,
            malicious_username,
        )
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

class BootstrapUsersCommandTests(TestCase):
    def test_password_environment_variables_are_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesMessage(
                CommandError,
                "OPSBOARD_ADMIN_PASSWORD must be set.",
            ):
                call_command("bootstrap_users")

    def test_command_is_idempotent_and_viewer_is_read_only(self):
        environment = {
            "OPSBOARD_ADMIN_PASSWORD": "test-admin-password",
            "OPSBOARD_VIEWER_PASSWORD": "test-viewer-password",
        }

        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ):
            call_command("bootstrap_users")
            call_command("bootstrap_users")

        User = get_user_model()

        self.assertEqual(
            User.objects.filter(
                username="opsboard-admin"
            ).count(),
            1,
        )
        self.assertEqual(
            User.objects.filter(
                username="opsboard-viewer"
            ).count(),
            1,
        )

        admin_user = User.objects.get(
            username="opsboard-admin"
        )
        viewer_user = User.objects.get(
            username="opsboard-viewer"
        )

        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(
            admin_user.check_password(
                "test-admin-password"
            )
        )

        self.assertTrue(viewer_user.is_staff)
        self.assertFalse(viewer_user.is_superuser)
        self.assertTrue(
            viewer_user.check_password(
                "test-viewer-password"
            )
        )
        self.assertTrue(
            viewer_user.has_perm(
                "dashboard.view_transaction"
            )
        )
        self.assertTrue(
            viewer_user.has_perm(
                "dashboard.view_dailymetric"
            )
        )
        self.assertFalse(
            viewer_user.has_perm(
                "dashboard.add_transaction"
            )
        )


class JWTAuthenticationTests(APITestCase):
    def setUp(self):
        self.password = "test-viewer-password"
        self.other_password = "other-password"
        self.user = get_user_model().objects.create_user(
            username="jwt-viewer",
            password=self.password,
        )
        self.other_user = (
            get_user_model().objects.create_user(
            username="other-jwt-user",
            password=self.other_password,
            )
        )

    def obtain_token_pair(self):
        return self.client.post(
            reverse("token_obtain_pair"),
            {
                "username": self.user.username,
                "password": self.password,
            },
            format="json",
        )

    def test_user_cannot_logout_another_users_token(self):
        own_pair_response = self.obtain_token_pair()
        other_pair_response = self.client.post(
            reverse("token_obtain_pair"),
            {
                "username": self.other_user.username,
                "password": self.other_password,
            },
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=(
                "Bearer "
                f"{own_pair_response.data['access']}"
            ),
        )
        logout_response = self.client.post(
            reverse("token_logout"),
            {
                "refresh": (
                    other_pair_response.data["refresh"]
                ),
            },
            format="json",
        )
        self.assertEqual(
            logout_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        refresh_response = self.client.post(
            reverse("token_refresh"),
            {
                "refresh": (
                    other_pair_response.data["refresh"]
                ),
            },
            format="json",
        )
        self.assertEqual(
            refresh_response.status_code,
            status.HTTP_200_OK,
        )

    def test_expired_access_token_is_rejected(self):
        access_token = AccessToken.for_user(
            self.user
        )
        access_token.set_exp(
            lifetime=timedelta(seconds=-1)
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=(
                f"Bearer {access_token}"
            ),
        )

        response = self.client.get(
            reverse("dashboard:daily_volume_chart")
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_token_cannot_authenticate_api_request(
        self,
        ):
        refresh_token = RefreshToken.for_user(
            self.user
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=(
                f"Bearer {refresh_token}"
            ),
        )
        response = self.client.get(
            reverse("dashboard:daily_volume_chart")
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_invalid_credentials_do_not_return_tokens(self):
        response = self.client.post(
            reverse("token_obtain_pair"),
            {
                "username": self.user.username,
                "password": "wrong-password",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)

    def test_valid_credentials_return_token_pair(self):
        response = self.obtain_token_pair()

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_logout_requires_authentication(self):
        pair_response = self.obtain_token_pair()

        response = self.client.post(
            reverse("token_logout"),
            {"refresh": pair_response.data["refresh"]},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_logout_revokes_refresh_token_family(self):
        pair_response = self.obtain_token_pair()
        access_token = pair_response.data["access"]
        refresh_token = pair_response.data["refresh"]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        logout_response = self.client.post(
            reverse("token_logout"),
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(
            logout_response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        refresh_response = self.client.post(
            reverse("token_refresh"),
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(
            refresh_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_logout_requires_refresh_token(self):
        pair_response = self.obtain_token_pair()
        access_token = pair_response.data["access"]

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        response = self.client.post(
            reverse("token_logout"),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("refresh", response.data)

    def test_session_cannot_authenticate_jwt_logout(self):
        csrf_client = APIClient(
            enforce_csrf_checks=True
        )
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            reverse("token_logout"),
            {"refresh": "unused-session-refresh"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_jwt_logout_does_not_require_csrf(self):
        csrf_client = APIClient(
            enforce_csrf_checks=True
        )

        pair_response = self.obtain_token_pair()
        access_token = pair_response.data["access"]
        refresh_token = pair_response.data["refresh"]

        csrf_client.credentials(
            HTTP_AUTHORIZATION=(
                f"Bearer {access_token}"
            ),
        )

        response = csrf_client.post(
            reverse("token_logout"),
            {"refresh": refresh_token},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_obtain_endpoint_stores_only_refresh_hash(self):
        pair_response = self.obtain_token_pair()

        self.assertEqual(
            pair_response.status_code,
            status.HTTP_200_OK,
        )

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )
        token_record = family.tokens.get()
        raw_refresh_token = pair_response.data["refresh"]

        self.assertEqual(
            token_record.token_hash,
            hash_refresh_token(raw_refresh_token),
        )
        self.assertNotEqual(
            token_record.token_hash,
            raw_refresh_token,
        )
        self.assertEqual(
            OutstandingToken.objects.count(),
            0,
        )

    def test_refresh_endpoint_rotates_refresh_token(self):
        pair_response = self.obtain_token_pair()
        original_refresh = pair_response.data["refresh"]

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )
        original_record = family.tokens.get()

        refresh_response = self.client.post(
            reverse("token_refresh"),
            {"refresh": original_refresh},
            format="json",
        )

        self.assertEqual(
            refresh_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIn("access", refresh_response.data)
        self.assertIn("refresh", refresh_response.data)
        self.assertNotEqual(
            refresh_response.data["refresh"],
            original_refresh,
        )

        original_record.refresh_from_db()
        replacement = original_record.replaced_by

        self.assertIsNotNone(original_record.used_at)
        self.assertIsNotNone(replacement)
        self.assertEqual(
            replacement.token_hash,
            hash_refresh_token(
                refresh_response.data["refresh"]
            ),
        )
        self.assertEqual(family.tokens.count(), 2)
        self.assertEqual(
            OutstandingToken.objects.count(),
            0,
        )

    def test_reusing_old_refresh_revokes_family(self):
        pair_response = self.obtain_token_pair()
        original_refresh = pair_response.data["refresh"]

        refresh_response = self.client.post(
            reverse("token_refresh"),
            {"refresh": original_refresh},
            format="json",
        )
        replacement_refresh = refresh_response.data["refresh"]

        reuse_response = self.client.post(
            reverse("token_refresh"),
            {"refresh": original_refresh},
            format="json",
        )

        self.assertEqual(
            reuse_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )
        family.refresh_from_db()

        self.assertIsNotNone(family.revoked_at)
        self.assertIsNotNone(
            family.reuse_detected_at
        )
        self.assertFalse(
            family.tokens.filter(
                revoked_at__isnull=True
            ).exists()
        )

        replacement_response = self.client.post(
            reverse("token_refresh"),
            {"refresh": replacement_refresh},
            format="json",
        )

        self.assertEqual(
            replacement_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(
            OutstandingToken.objects.count(),
            0,
        )


class StepUpAuthenticationTests(APITestCase):
    def setUp(self):
        self.admin_password = "admin-step-up-password"
        self.viewer_password = "viewer-step-up-password"

        self.admin = get_user_model().objects.create_superuser(
            username="step-up-admin",
            password=self.admin_password,
            email="admin@example.com",
        )
        self.viewer = get_user_model().objects.create_user(
            username="step-up-viewer",
            password=self.viewer_password,
        )

        Transaction.objects.create(
            user=self.viewer,
            amount=Decimal("125.50000000"),
            currency=Transaction.Currency.USD,
            status=Transaction.Status.COMPLETED,
        )

    def authenticate_with_jwt(self, user, password):
        pair_response = self.client.post(
            reverse("token_obtain_pair"),
            {
                "username": user.username,
                "password": password,
            },
            format="json",
        )
        self.assertEqual(
            pair_response.status_code,
            status.HTTP_200_OK,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=(
                f"Bearer {pair_response.data['access']}"
            )
        )

    def test_export_requires_jwt_authentication(self):
        response = self.client.post(
            reverse("dashboard:transaction_api_export"),
            {"password": self.admin_password},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_session_cannot_authenticate_export_api(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("dashboard:transaction_api_export"),
            {"password": self.admin_password},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_viewer_cannot_export_with_correct_password(self):
        self.authenticate_with_jwt(
            self.viewer,
            self.viewer_password,
        )

        response = self.client.post(
            reverse("dashboard:transaction_api_export"),
            {"password": self.viewer_password},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_access_token_alone_is_not_enough(self):
        self.authenticate_with_jwt(
            self.admin,
            self.admin_password,
        )

        response = self.client.post(
            reverse("dashboard:transaction_api_export"),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("password", response.data)

    def test_admin_with_wrong_password_is_rejected(self):
        self.authenticate_with_jwt(
            self.admin,
            self.admin_password,
        )

        response = self.client.post(
            reverse("dashboard:transaction_api_export"),
            {"password": "wrong-password"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_with_step_up_password_can_export(self):
        self.authenticate_with_jwt(
            self.admin,
            self.admin_password,
        )

        response = self.client.post(
            reverse("dashboard:transaction_api_export"),
            {"password": self.admin_password},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["total_transactions"], 1)
        self.assertEqual(response.data["exported_transactions"], 1)
        self.assertFalse(response.data["truncated"])
        self.assertEqual(len(response.data["results"]), 1)
        self.assertNotContains(
            response,
            self.admin_password,
        )


class TransactionDetailAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.viewer = user_model.objects.create_user(
            username="api-viewer",
            password="viewer-password",
        )
        cls.viewer.user_permissions.add(
            Permission.objects.get(
                codename="view_transaction",
                content_type__app_label="dashboard",
            )
        )

        cls.admin = user_model.objects.create_superuser(
            username="api-admin",
            email="admin@example.com",
            password="admin-password",
        )

        cls.transaction = Transaction.objects.create(
            user=cls.viewer,
            amount=Decimal("25.00000000"),
            currency=Transaction.Currency.USD,
            status=Transaction.Status.PENDING,
        )

        cls.url = reverse(
            "dashboard:transaction_api_detail",
            kwargs={
                "reference": cls.transaction.reference,
            },
        )

    def authenticate_as(self, user):
        access_token = RefreshToken.for_user(
            user
        ).access_token

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

    def test_anonymous_user_cannot_read_transaction(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_viewer_can_read_transaction(self):
        self.authenticate_as(self.viewer)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["reference"],
            str(self.transaction.reference),
        )

    def test_viewer_cannot_change_transaction(self):
        self.authenticate_as(self.viewer)

        response = self.client.patch(
            self.url,
            {"status": Transaction.Status.COMPLETED},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.transaction.refresh_from_db()
        self.assertEqual(
            self.transaction.status,
            Transaction.Status.PENDING,
        )

    def test_admin_can_change_transaction_status(self):
        self.authenticate_as(self.admin)

        response = self.client.patch(
            self.url,
            {"status": Transaction.Status.COMPLETED},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.transaction.refresh_from_db()
        self.assertEqual(
            self.transaction.status,
            Transaction.Status.COMPLETED,
        )
class TransactionListAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.viewer = user_model.objects.create_user(
            username="Ashutosh",
            password="Python@123",
        )
        cls.viewer.user_permissions.add(
            Permission.objects.get(
                codename="view_transaction",
                content_type__app_label="dashboard",
            )
        )

        Transaction.objects.bulk_create(
            [
                Transaction(
                    user=cls.viewer,
                    amount=Decimal("10.00000000"),
                    currency=Transaction.Currency.USD,
                    status=Transaction.Status.COMPLETED,
                )
                for _ in range(125)
            ]
        )

        Transaction.objects.bulk_create(
            [
                Transaction(
                     user=cls.viewer,
                     amount=Decimal("1.00000000"),
                     currency=Transaction.Currency.BTC,
                     status=Transaction.Status.COMPLETED,
                 )
                 for _ in range(3)
            ]
)

        cls.url = reverse(
            "dashboard:transaction_api_list"
        )

    def setUp(self):
        self.client.force_authenticate(
            user=self.viewer
        )

    def test_default_page_contains_25_transactions(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["count"], 128)
        self.assertEqual(
            len(response.data["results"]),
            25,
        )
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_requested_page_size_is_capped_at_100(self):
        response = self.client.get(
            self.url,
            {"page_size": 200},
        )

        self.assertEqual(
            len(response.data["results"]),
            100,
        )

    def test_list_query_count_does_not_grow_per_user(self):
        self.viewer.has_perm(
            "dashboard.view_transaction"
        )

        with self.assertNumQueries(2):
            response = self.client.get(
                self.url,
                {"page_size": 100},
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_list_can_be_filtered_by_currency(self):
        response = self.client.get(
            self.url,
            {"currency": Transaction.Currency.BTC},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["count"], 3)

        self.assertTrue(
            all(
                transaction["currency"]
                == Transaction.Currency.BTC
                for transaction in response.data["results"]
            )
        )
    def test_currency_filter_does_not_execute_sql_input(
        self,
    ):
        malicious_value = "USD' OR 1=1 --"

        response = self.client.get(
            self.url,
            {"currency": malicious_value},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])
        
class MoneyFieldConfigurationTests(TestCase):
    def test_money_fields_use_decimal_with_explicit_precision(self):
        money_fields = [
            (Transaction, "amount"),
            (DailyMetric, "total_volume"),
        ]

        for model_class, field_name in money_fields:
            with self.subTest(
                model=model_class.__name__,
                field=field_name,
            ):
                field = model_class._meta.get_field(field_name)

                self.assertIsInstance(
                    field,
                    models.DecimalField,
                )
                self.assertEqual(field.max_digits, 20)
                self.assertEqual(field.decimal_places, 8)
                
class RefreshTokenModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="token-model-user",
            password="test-password-2026",
        )
        self.family = RefreshTokenFamily.objects.create(
            user=self.user,
        )

    def create_token_record(self, token_value):
        token_hash = hashlib.sha256(
            token_value.encode("utf-8")
        ).hexdigest()

        return HashedRefreshToken.objects.create(
            family=self.family,
            jti=uuid.uuid4(),
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_new_family_starts_active(self):
        self.assertEqual(self.family.user, self.user)
        self.assertIsNotNone(self.family.id)
        self.assertIsNone(self.family.revoked_at)
        self.assertIsNone(self.family.reuse_detected_at)

    def test_token_record_stores_hash_not_raw_value(self):
        raw_token = "high-entropy-test-refresh-token"

        token_record = self.create_token_record(raw_token)

        expected_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        self.assertEqual(
            token_record.token_hash,
            expected_hash,
        )
        self.assertNotEqual(
            token_record.token_hash,
            raw_token,
        )
        self.assertEqual(len(token_record.token_hash), 64)
        self.assertIsNone(token_record.used_at)
        self.assertIsNone(token_record.revoked_at)

    def test_model_has_no_raw_token_field(self):
        field_names = {
            field.name
            for field in HashedRefreshToken._meta.fields
        }

        self.assertNotIn("token", field_names)
        self.assertNotIn("raw_token", field_names)
        self.assertNotIn("refresh_token", field_names)

    def test_token_can_point_to_its_replacement(self):
        old_token = self.create_token_record("old-refresh-token")
        replacement = self.create_token_record(
            "replacement-refresh-token"
        )

        old_token.replaced_by = replacement
        old_token.save(update_fields=["replaced_by"])
        old_token.refresh_from_db()

        self.assertEqual(old_token.replaced_by, replacement)
        self.assertEqual(replacement.replaces, old_token)

    def test_deleting_family_deletes_its_token_records(self):
        token_record = self.create_token_record(
            "refresh-token-for-deletion-test"
        )
        token_id = token_record.id

        self.family.delete()

        self.assertFalse(
            HashedRefreshToken.objects.filter(
                id=token_id
            ).exists()
        )
        
class TokenIssuanceServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="token-service-user",
            password="test-password-2026",
        )

    def test_issuance_returns_valid_access_and_refresh_tokens(self):
        token_pair = issue_token_pair(self.user)

        access_token = AccessToken(token_pair["access"])
        refresh_token = RotatingRefreshToken(
            token_pair["refresh"]
        )

        user_id_claim = api_settings.USER_ID_CLAIM

        self.assertEqual(
            str(access_token[user_id_claim]),
            str(self.user.pk),
        )
        self.assertEqual(
            str(refresh_token[user_id_claim]),
            str(self.user.pk),
        )
        self.assertEqual(
            access_token["token_type"],
            "access",
        )
        self.assertEqual(
            refresh_token["token_type"],
            "refresh",
        )

    def test_issuance_stores_only_refresh_token_hash(self):
        token_pair = issue_token_pair(self.user)
        raw_refresh_token = token_pair["refresh"]

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )
        token_record = HashedRefreshToken.objects.get(
            family=family
        )
        decoded_refresh = RotatingRefreshToken(
            raw_refresh_token
        )

        self.assertEqual(
            token_record.token_hash,
            hash_refresh_token(raw_refresh_token),
        )
        self.assertNotEqual(
            token_record.token_hash,
            raw_refresh_token,
        )
        self.assertEqual(
            token_record.jti,
            uuid.UUID(decoded_refresh["jti"]),
        )
        self.assertEqual(
            str(family.id),
            decoded_refresh["family_id"],
        )
        self.assertEqual(
            int(token_record.expires_at.timestamp()),
            decoded_refresh["exp"],
        )

    def test_access_and_refresh_share_family_identifier(self):
        token_pair = issue_token_pair(self.user)

        access_token = AccessToken(token_pair["access"])
        refresh_token = RotatingRefreshToken(
            token_pair["refresh"]
        )

        self.assertEqual(
            access_token["family_id"],
            refresh_token["family_id"],
        )

    def test_custom_issuance_does_not_create_outstanding_token(self):
        self.assertEqual(
            OutstandingToken.objects.count(),
            0,
        )

        issue_token_pair(self.user)

        self.assertEqual(
            OutstandingToken.objects.count(),
            0,
        )

    def test_inactive_user_cannot_receive_tokens(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with self.assertRaises(ValueError):
            issue_token_pair(self.user)

        self.assertFalse(
            RefreshTokenFamily.objects.filter(
                user=self.user
            ).exists()
        )
        self.assertFalse(
            HashedRefreshToken.objects.filter(
                family__user=self.user
            ).exists()
        )
        self.assertEqual(
            OutstandingToken.objects.count(),
            0,
        )
    
class RefreshTokenRotationServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rotation-user",
            password="test-password-2026",
        )

    def test_rotation_retires_old_token_and_creates_replacement(self):
        first_pair = issue_token_pair(self.user)

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )
        old_record = family.tokens.get()

        second_pair = rotate_refresh_token(
            first_pair["refresh"]
        )

        old_record.refresh_from_db()
        family.refresh_from_db()

        replacement = old_record.replaced_by

        self.assertIsNotNone(old_record.used_at)
        self.assertIsNotNone(replacement)
        self.assertEqual(
            replacement.family,
            family,
        )
        self.assertEqual(
            replacement.token_hash,
            hash_refresh_token(
                second_pair["refresh"]
            ),
        )
        self.assertEqual(family.tokens.count(), 2)
        self.assertIsNone(family.revoked_at)
        self.assertIsNone(family.reuse_detected_at)
        self.assertEqual(
            OutstandingToken.objects.count(),
            0,
        )

    def test_reusing_retired_token_revokes_entire_family(self):
        first_pair = issue_token_pair(self.user)
        second_pair = rotate_refresh_token(
            first_pair["refresh"]
        )

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )

        with self.assertLogs(
            "dashboard.token_service",
            level="WARNING",
        ) as captured_logs:
            with self.assertRaises(
                RefreshTokenReuseDetected
            ):
                rotate_refresh_token(
                    first_pair["refresh"]
                )

        family.refresh_from_db()

        self.assertIsNotNone(family.revoked_at)
        self.assertIsNotNone(
            family.reuse_detected_at
        )
        self.assertFalse(
            family.tokens.filter(
                revoked_at__isnull=True
            ).exists()
        )
        self.assertNotIn(
            first_pair["refresh"],
            "\n".join(captured_logs.output),
        )

        with self.assertRaises(TokenError):
            rotate_refresh_token(
                second_pair["refresh"]
            )

    def test_inactive_user_rotation_revokes_family(self):
        token_pair = issue_token_pair(self.user)
        family = RefreshTokenFamily.objects.get(
            user=self.user
        )

        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with self.assertRaises(TokenError):
            rotate_refresh_token(
                token_pair["refresh"]
            )

        family.refresh_from_db()

        self.assertIsNotNone(family.revoked_at)
        self.assertFalse(
            family.tokens.filter(
                revoked_at__isnull=True
            ).exists()
        )

    def test_random_token_string_is_rejected(self):
        with self.assertRaises(TokenError):
            rotate_refresh_token(
                "not-a-signed-refresh-token"
            )


class RefreshTokenLogoutServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="logout-service-user",
            password="test-password-2026",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-logout-user",
            password="test-password-2026",
        )

    def test_logout_revokes_entire_token_family(self):
        first_pair = issue_token_pair(self.user)
        second_pair = rotate_refresh_token(
            first_pair["refresh"]
        )

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )

        revoke_refresh_token_family(
            second_pair["refresh"],
            self.user,
        )

        family.refresh_from_db()

        self.assertIsNotNone(family.revoked_at)
        self.assertFalse(
            family.tokens.filter(
                revoked_at__isnull=True
            ).exists()
        )

        with self.assertRaises(TokenError):
            rotate_refresh_token(
                second_pair["refresh"]
            )

    def test_user_cannot_revoke_another_users_family(self):
        token_pair = issue_token_pair(self.user)
        family = RefreshTokenFamily.objects.get(
            user=self.user
        )

        with self.assertRaises(
            RefreshTokenOwnershipError
        ):
            revoke_refresh_token_family(
                token_pair["refresh"],
                self.other_user,
            )

        family.refresh_from_db()

        self.assertIsNone(family.revoked_at)
        self.assertTrue(
            family.tokens.filter(
                revoked_at__isnull=True
            ).exists()
        )

    def test_logout_is_idempotent(self):
        token_pair = issue_token_pair(self.user)

        revoke_refresh_token_family(
            token_pair["refresh"],
            self.user,
        )
        revoke_refresh_token_family(
            token_pair["refresh"],
            self.user,
        )

        family = RefreshTokenFamily.objects.get(
            user=self.user
        )

        self.assertIsNotNone(family.revoked_at)
        self.assertFalse(
            family.tokens.filter(
                revoked_at__isnull=True
            ).exists()
        )
