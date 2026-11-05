"""योजनाको डाटा मात्र मेटाउने (अभ्यास / नयाँ सुरुवातका लागि) — पहिले ब्याकअप बन्छ.

    python manage.py reset_projects --schema bagmati          # के मेटिन्छ मात्र देखाउने (केही मेटिँदैन)
    python manage.py reset_projects --schema bagmati --yes    # ब्याकअप बनाएर मेटाउने

मेटिने: योजना (Project) र त्यससँग जोडिएका सबै — उपभोक्ता समिति, लागत अनुमान, बोलपत्र, दरभाउपत्र, सोझै / अमानत /
संस्था, नापी किताब, भुक्तानी, कट्टी, जमानत, साइट फोटो, खरिद योजना, आ.व. बन्दका अभिलेख.
रहने: प्रयोगकर्ता, वडा, आर्थिक वर्ष, बजेट शीर्षक, फर्म सूची, राजस्व ठेक्का, सबै सेटिङ, गतिविधि लग.
"""
from collections import Counter

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import router, transaction
from django.db.models.deletion import Collector
from django_tenants.utils import tenant_context


def _count(qs):
    c = Collector(using=router.db_for_write(qs.model))
    c.collect(qs)
    out = Counter()
    for model, objs in c.data.items():
        out[model._meta.label] += len(objs)
    for qs_ in c.fast_deletes:
        out[qs_.model._meta.label] += qs_.count()
    return out


class Command(BaseCommand):
    help = "एउटा पालिकाको योजनाको डाटा मेटाउने (पहिले ब्याकअप)"

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="पालिकाको schema, जस्तै bagmati")
        parser.add_argument("--yes", action="store_true", help="साँच्चै मेटाउने (नदिए के मेटिन्छ मात्र देखाउँछ)")
        parser.add_argument("--no-backup", action="store_true", help="ब्याकअप नबनाउने (सिफारिस होइन)")

    def handle(self, *args, **o):
        from tenants.models import Palika

        pal = Palika.objects.filter(schema_name=o["schema"]).first()
        if pal is None or pal.schema_name == "public":
            raise CommandError(f"पालिका '{o['schema']}' भेटिएन।")
        with tenant_context(pal):
            from projects.models import Project, YearEndLine

            total = Counter()
            total += _count(YearEndLine.objects.all())
            total += _count(Project.objects.all())
            self.stdout.write(f"पालिका: {pal.schema_name} — मेटिने रेकर्ड:")
            for label, n in sorted(total.items(), key=lambda kv: -kv[1]):
                if n:
                    self.stdout.write(f"  {n:>7}  {label}")
            self.stdout.write(f"  जम्मा {sum(total.values())} रेकर्ड। प्रयोगकर्ता, वडा, आ.व., फर्म, राजस्व र सेटिङ रहन्छन्।")
            if not o["yes"]:
                self.stdout.write(self.style.WARNING("केही मेटिएन। साँच्चै मेटाउन --yes थप्नुहोस्।"))
                return
            if not o["no_backup"]:
                from projects import backup

                path, c = backup.make_backup(pal.schema_name)
                self.stdout.write(self.style.SUCCESS(f"ब्याकअप: {path} ({c['objects']} रेकर्ड, {c['files']} फाइल)"))
            with transaction.atomic():
                YearEndLine.objects.all().delete()
                Project.objects.all().delete()
                from projects.models import FiscalYear

                FiscalYear.objects.update(closed_at=None, closed_by=None, close_ref="")
            try:
                from usercommittee.models import ActivityLog

                ActivityLog.objects.create(action="delete", model_name="योजना डाटा", object_repr="reset_projects",
                                           note=f"{sum(total.values())} रेकर्ड मेटाइयो")
            except Exception:
                pass
            cache.clear()
            self.stdout.write(self.style.SUCCESS("योजनाको डाटा मेटियो। अब आयोजना बैंकबाट नयाँ सुरु गर्नुहोस्।"))
