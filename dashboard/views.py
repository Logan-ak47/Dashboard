from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum

from datetime import  datetime, time, timedelta
from .models import DailyMetric, Transaction
from decimal import Decimal
from uuid import UUID



@login_required
def home(request: HttpRequest) -> HttpResponse:
    summary=Transaction.objects.aggregate(
        total_transactions=Count("id"),
        completed_transactions=Count(
            "id",
            filter=Q(status=Transaction.Status.COMPLETED),
        ),
        completed_volume=Sum(
            "amount",
            filter=Q(status=Transaction.Status.COMPLETED),
        ),
    )
    summary["completed_volume"]=(
        summary["completed_volume"]
        or Decimal("0")
    )

    return render(
        request,
        "dashboard/home.html",
        {
            "summary":summary,
            "currency_choices":Transaction.Currency.choices,
         }
    )

@login_required
def daily_volume_chart(request:HttpRequest)->JsonResponse:
    start_date=timezone.localdate() - timedelta(days=29)
    metric_rows=list(
        DailyMetric.objects
        .filter(date__gte=start_date)
        .values("date","currency","total_volume")
        .order_by("date","currency")
    )
    dates=sorted({
        row["date"]
        for row in metric_rows
    })
    volume_by_currency={
        currency:{}
        for currency in Transaction.Currency.values
    }
    for row in metric_rows:
         volume_by_currency[row["currency"]][row["date"]] = float(
            row["total_volume"]
         )

    datasets=[
        {
            "label":currency,
            "data":[
                volume_by_currency[currency].get(date,0)
                for date in dates
            ],
        }
        for currency in Transaction.Currency.values
    ]

    return JsonResponse({
        "labels":[
            date.isoformat()
            for date in dates
        ],
        "datasets":datasets,
    })


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
