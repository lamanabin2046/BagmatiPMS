"""
One-time setup of the SaaS manager.

    python manage.py migrate_schemas --shared
    python manage.py setup_saas --mobile 98XXXXXXXX --password <pw>

Creates the public tenant for BASE_DOMAIN and a SaaS manager login.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import CustomUser
from tenants.provisioning import ensure_public_tenant


class Command(BaseCommand):
    help = "Create the public (SaaS manager) tenant and a SaaS manager user."

    def add_arguments(self, parser):
        parser.add_argument("--mobile", required=True)
        parser.add_argument("--password", required=True)

    def handle(self, *args, **o):
        ensure_public_tenant(settings.BASE_DOMAIN)
        user = CustomUser.objects.filter(mobile=o["mobile"]).first()
        if user is None:
            CustomUser.objects.create_superuser(mobile=o["mobile"], password=o["password"])
            self.stdout.write(self.style.SUCCESS(f"SaaS manager user {o['mobile']} created."))
        else:
            user.set_password(o["password"])
            user.is_superuser = user.is_staff = user.is_active = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"SaaS manager user {o['mobile']} updated."))
        self.stdout.write(f"Open http://{settings.BASE_DOMAIN}:8000/ and log in.")
