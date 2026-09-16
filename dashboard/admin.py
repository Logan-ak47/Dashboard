from django.contrib import admin

# Register your models here.
from .models import DailyMetric,Transaction

@admin.register(DailyMetric)
class DailyMetricAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "currency",
        "transaction_count",
        "total_volume",
    )
    list_filter = ("currency",)
    date_hierarchy = "date"
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (

        "reference", 
        "user",
        "amount",
        "currency",
        "status",
        "timestamp"
    )
    list_filter = (
        "status",
        "currency",
    )
    search_fields = (
        "=reference",
        "user__username",
    )
    list_select_related = (
        "user",
    )
    date_hierarchy = "timestamp"
    
