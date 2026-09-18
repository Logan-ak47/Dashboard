from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("transactions/",
          views.TransactionListView.as_view(),
          name="transaction_list"
        ),
]
