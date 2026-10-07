from django.urls import path

from . import views
from .api_views import (
    TransactionDetailAPIView,
    TransactionListAPIView,
)

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("transactions/",
          views.TransactionListView.as_view(),
          name="transaction_list"
        ),
    path(
        "api/charts/daily-volume/",
        views.daily_volume_chart,
        name="daily_volume_chart"
    ),
    path(
        "api/transactions/<uuid:reference>/",
        TransactionDetailAPIView.as_view(),
        name="transaction_api_detail",
    ),
    path(
    "api/transactions/",
    TransactionListAPIView.as_view(),
    name="transaction_api_list",
    ),
]
