"""
Move the old single-palika SQLite data (db.sqlite3) into one palika's schema.

    python manage.py import_sqlite --code bagmati --sqlite db.sqlite3

The palika must already exist (create_palika). Its default lookup rows are replaced
by the old data so all ids stay exactly the same. Uploaded files in media/ are copied
to media/<code>/ so the new per-palika storage finds them.
"""
import shutil
import sqlite3
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from tenants.models import Palika

# Tables copied, in dependency order.
MODELS = [
    "accounts.CustomUser", "accounts.Ward",
    "accounts.Admin", "accounts.Cao", "accounts.PlanningOfficer", "accounts.Engineer",
    "accounts.WadaStaff", "accounts.WardSachib", "accounts.WardEngineer", "accounts.PalikaEngineer",
    "projects.FiscalYear", "projects.Project_Type", "projects.Budget_Type", "projects.Procurement_Type",
    "projects.Project", "projects.ProjectTimeline",
    "usercommittee.UserCommittee", "usercommittee.CostEstimate", "usercommittee.FinalPayment",
    "usercommittee.WardRecommendation", "usercommittee.ProjectCompletionRecommendation",
    "usercommittee.SiteInspectionNote", "usercommittee.ActivityLog",
    "biddings.SealedBid", "biddings.Contract", "biddings.ContractExtension",
    "biddings.PerformanceBondRequirement", "biddings.PerformanceBondIssued",
    "biddings.PerformanceBondExtension", "biddings.AdvancePayment", "biddings.AdvanceBankGuarantee",
    "biddings.FinalPayment", "biddings.RunningEvaluation",
    "quatation.Suchikrit", "quatation.Quation", "quatation.QuationFinal",
]


class Command(BaseCommand):
    help = "Import the old SQLite database into one palika's schema."

    def add_arguments(self, parser):
        parser.add_argument("--code", required=True)
        parser.add_argument("--sqlite", default=str(settings.BASE_DIR / "db.sqlite3"))
        parser.add_argument("--force", action="store_true", help="import even if the palika already has projects")

    def handle(self, *args, **o):
        palika = Palika.objects.filter(schema_name=o["code"]).first()
        if palika is None:
            raise CommandError(f"Palika '{o['code']}' not found. Run create_palika first.")
        src = sqlite3.connect(o["sqlite"])
        src.row_factory = sqlite3.Row
        src_tables = {r[0] for r in src.execute("select name from sqlite_master where type='table'")}

        with schema_context(palika.schema_name):
            Project = apps.get_model("projects.Project")
            if Project.objects.exists() and not o["force"]:
                raise CommandError("This palika already has projects. Use --force to replace its data.")
            with transaction.atomic():
                # wipe in reverse order (removes provisioning defaults so ids match the old data)
                for label in reversed(MODELS):
                    apps.get_model(label).objects.all().delete()
                for label in MODELS:
                    self.copy_table(src, src_tables, apps.get_model(label))
                self.reset_sequences()

        self.copy_media(palika.schema_name)
        self.stdout.write(self.style.SUCCESS(f"Imported into '{palika.schema_name}'."))

    def copy_table(self, src, src_tables, model):
        table = model._meta.db_table
        if table not in src_tables:
            self.stdout.write(f"  skip {table} (not in sqlite)")
            return
        src_cols = {r[1] for r in src.execute(f'pragma table_info("{table}")')}
        fields = [f for f in model._meta.concrete_fields if f.column in src_cols]
        rows = src.execute(f'select {", ".join(chr(34)+f.column+chr(34) for f in fields)} from "{table}"').fetchall()
        objs = []
        for r in rows:
            data = {}
            for f in fields:
                v = r[f.column]
                if v is not None and not f.is_relation:
                    v = f.to_python(v)
                    # SQLite stored UTC without a timezone
                    if isinstance(v, datetime) and timezone.is_naive(v):
                        v = timezone.make_aware(v, dt_timezone.utc)
                data[f.attname] = v
            objs.append(model(**data))
        model.objects.bulk_create(objs, batch_size=500)
        # many-to-many tables
        for m2m in model._meta.many_to_many:
            through = m2m.remote_field.through
            if m2m.related_model._meta.app_label in ("auth", "contenttypes"):
                continue  # Django permissions/groups are recreated, not copied
            if through._meta.auto_created and through._meta.db_table in src_tables:
                t = through._meta.db_table
                cols = [f.column for f in through._meta.concrete_fields if not f.primary_key]
                links = src.execute(f'select {", ".join(cols)} from "{t}"').fetchall()
                attn = [f.attname for f in through._meta.concrete_fields if not f.primary_key]
                through.objects.bulk_create([through(**dict(zip(attn, l))) for l in links])
                self.stdout.write(f"  {t}: {len(links)}")
        self.stdout.write(f"  {table}: {len(objs)}")

    def reset_sequences(self):
        from django.core.management.color import no_style

        models = [apps.get_model(l) for l in MODELS]
        models += [m2m.remote_field.through for m in models for m2m in m._meta.many_to_many]
        with connection.cursor() as c:
            for sql in connection.ops.sequence_reset_sql(no_style(), models):
                c.execute(sql)

    def copy_media(self, schema):
        root = Path(settings.MEDIA_ROOT)
        dest = root / schema
        skip = {schema, "palika_logos", "public"}
        moved = 0
        for item in list(root.iterdir()) if root.exists() else []:
            if item.name in skip or (item.is_dir() and (item / ".tenant_dir").exists()):
                continue
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
            moved += 1
        self.stdout.write(f"  media: copied {moved} item(s) into media/{schema}/ (originals kept)")
