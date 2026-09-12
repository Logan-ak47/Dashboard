from django.test import TestCase
from django.urls import reverse


class HomeViewTests(TestCase):
    def test_home_page_renders(self) -> None:
        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OpsBoard")
        self.assertTemplateUsed(response, "dashboard/home.html")
