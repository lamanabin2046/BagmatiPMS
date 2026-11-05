from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import Domain, Palika


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 0


@admin.register(Palika)
class PalikaAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("full_name", "schema_name", "district", "plan", "is_active", "paid_until")
    list_filter = ("is_active", "plan", "palika_type")
    search_fields = ("name", "name_en", "schema_name", "district")
    inlines = [DomainInline]
