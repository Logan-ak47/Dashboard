from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.utils import timezone
from django.utils.dateparse import parse_date

from datetime import datetime, time, timedelta
from .models import Transaction

from uuid import UUID

from django.db.models import Q


def home(request: HttpRequest) -> HttpResponse:
    """Render the initial OpsBoard landing page."""
    return render(request, "dashboard/home.html")

class TransactionListView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name ="dashboard/transaction_list.html"
    context_object_name = "transactions"
    paginate_by = 50  # Number of transactions per page

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("user")
        )

        selected_status = self.request.GET.get("status", "")

        if selected_status in Transaction.Status.values:
            queryset = queryset.filter(status=selected_status)

        date_from = parse_date(
            self.request.GET.get("date_from", "")
        )
        date_to = parse_date(
            self.request.GET.get("date_to", "")
        )

        current_timezone = timezone.get_current_timezone()

        if date_from is not None:
            start_timestamp = timezone.make_aware(
                datetime.combine(date_from, time.min),
                current_timezone,
            )
            queryset = queryset.filter(
                timestamp__gte=start_timestamp
            )

        if date_to is not None:
            end_timestamp = timezone.make_aware(
                datetime.combine(
                    date_to + timedelta(days=1),
                    time.min,
                ),
                current_timezone,
            )
            queryset = queryset.filter(
                timestamp__lt=end_timestamp
            )

        search_term = self.request.GET.get(
            "search",
            "",
        ).strip()

        if search_term:
            search_query = Q(
                user__username__icontains=search_term
            )

            try:
                reference = UUID(search_term)
            except ValueError:
                pass
            else:
                search_query |= Q(reference=reference)
            queryset = queryset.filter(search_query)
        return queryset
    def get_context_data(self, **kwargs):
        context=super().get_context_data(**kwargs)
        context["status_choices"] = Transaction.Status.choices
        context["selected_status"] = self.request.GET.get("status","")
        context["date_from"] = self.request.GET.get("date_from", "")
        context["date_to"] = self.request.GET.get("date_to", "")
        context["search"] = self.request.GET.get("search", "")
        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        context["query_string"] = query_params.urlencode()
        return context
