from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse


class HomeViewTests(TestCase):
    def test_home_page_renders(self) -> None:
        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OpsBoard")
        self.assertTemplateUsed(response, "dashboard/home.html")

class AdminPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls)-> None:
        viewer_group=Group.objects.create(name="Viewer")
        view_transaction=Permission.objects.get(
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

    def test_viewer_can_view_transaction_list(self)->None:
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("admin:dashboard_transaction_changelist")
        )
        self.assertEqual(response.status_code, 200)

    def test_viewer_cannot_add_transaction(self)->None:
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse("admin:dashboard_transaction_add")
        )
        self.assertEqual(response.status_code, 403)
