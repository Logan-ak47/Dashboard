from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    """Render the initial OpsBoard landing page."""
    return render(request, "dashboard/home.html")
