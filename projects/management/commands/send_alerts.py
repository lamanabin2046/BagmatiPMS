"""SMS / इमेल सूचना — cron मा दिनहुँ बिहान चलाउने:
    python manage.py send_alerts                 # सबै सक्रिय पालिका
    python manage.py send_alerts --schema bagmati --dry   # के पठाइन्छ मात्र हेर्ने
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import tenant_context

from projects import notify


class Command(BaseCommand):
    help = "कर्मचारी र राजस्व ठेकेदारलाई SMS / इमेल सूचना"

    def add_arguments(self, parser):
        parser.add_argument("--schema", help="एउटा पालिका मात्र")
        parser.add_argument("--dry", action="store_true", help="नपठाई गन्ती मात्र")

    def handle(self, *args, **opts):
        from tenants.models import Palika

        qs = Palika.objects.exclude(schema_name="public")
        qs = qs.filter(schema_name=opts["schema"]) if opts.get("schema") else qs.filter(is_active=True)
        failed = 0
        for p in qs:
            try:
                with tenant_context(p):
                    c = notify.run(dry=opts["dry"])
                self.stdout.write(f"✓ {p.schema_name}: {c}")
            except Exception as e:
                failed += 1
                self.stderr.write(f"✗ {p.schema_name}: {e}")
        if failed:
            raise SystemExit(1)
