"""सबै (वा एउटा) पालिकाको ब्याकअप — cron मा दिनहुँ चलाउने:
    python manage.py backup_palikas            # सबै सक्रिय पालिका
    python manage.py backup_palikas --schema bagmati
"""
from django.core.management.base import BaseCommand

from projects import backup


class Command(BaseCommand):
    help = "पालिकाको डाटा र अपलोड फाइलको ब्याकअप (zip)"

    def add_arguments(self, parser):
        parser.add_argument("--schema", help="एउटा पालिका मात्र")

    def handle(self, *args, **opts):
        from tenants.models import Palika

        qs = Palika.objects.exclude(schema_name="public")
        if opts.get("schema"):
            qs = qs.filter(schema_name=opts["schema"])
        else:
            qs = qs.filter(is_active=True)
        failed = 0
        for p in qs:
            try:
                path, c = backup.make_backup(p.schema_name)
                self.stdout.write(f"✓ {p.schema_name}: {path.name} ({c['objects']} रेकर्ड, {c['files']} फाइल)")
            except Exception as e:  # एउटा असफल भए पनि अरू चलोस्
                failed += 1
                self.stderr.write(f"✗ {p.schema_name}: {e}")
        if failed:
            raise SystemExit(1)
