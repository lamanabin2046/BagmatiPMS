"""
Create a palika from the command line (same as the SaaS manager form).

    python manage.py create_palika --code bagmati --name बागमती --district ललितपुर \
        --address भट्टेडाँडा --wards 7 --admin-mobile 9845184845
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tenants.models import Palika
from tenants.provisioning import create_palika, provision_palika


class Command(BaseCommand):
    help = "Create a palika: its own schema, tables, admin user and default data."

    def add_arguments(self, parser):
        parser.add_argument("--code", required=True, help="schema / subdomain, e.g. bagmati")
        parser.add_argument("--name", required=True, help="Nepali name without type, e.g. बागमती")
        parser.add_argument("--type", default="गाउँपालिका")
        parser.add_argument("--name-en", default="")
        parser.add_argument("--district", default="")
        parser.add_argument("--address", default="")
        parser.add_argument("--province", default="बागमती प्रदेश")
        parser.add_argument("--wards", type=int, default=0)
        parser.add_argument("--admin-mobile", required=True)
        parser.add_argument("--admin-password", default=None)

    def handle(self, *args, **o):
        code = o["code"].lower()
        palika = Palika.objects.filter(schema_name=code).first()
        if palika is None:
            self.stdout.write(f"Creating schema '{code}' and tables (this takes a little while)...")
            palika = create_palika(
                schema_name=code, name=o["name"], base_domain=settings.BASE_DOMAIN,
                palika_type=o["type"], name_en=o["name_en"], district=o["district"],
                address=o["address"], province=o["province"],
            )
        else:
            self.stdout.write(f"Palika '{code}' exists; making sure its setup is complete.")
        password = provision_palika(
            palika, admin_mobile=o["admin_mobile"], admin_password=o["admin_password"],
            number_of_wards=o["wards"],
        )
        self.stdout.write(self.style.SUCCESS(f"\n{palika.full_name} is ready."))
        site = (f"https://{palika.primary_domain}/" if not settings.DEBUG
                else f"http://{palika.primary_domain}:8000/")
        self.stdout.write(f"  Site:     {site}")
        self.stdout.write(f"  Login:    {o['admin_mobile']}")
        self.stdout.write(f"  Password: {password}")
