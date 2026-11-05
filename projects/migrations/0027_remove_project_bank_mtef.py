"""आयोजना बैंक र MTEF हटाइयो — त्यसका तालिका, Project.bank_project / outside_bank_reason र अनुमति (भूमिका / व्यक्तिगत).

पुरानो अवस्था चाहिए: git branch `with-project-bank`.
"""
from django.db import migrations

OLD_PERMS = ["bank.view", "bank.propose", "bank.ward_priority", "bank.screen", "bank.manage",
             "mtef.manage", "mtef.approve", "plan.settings"]


def drop_perms(apps, schema_editor):
    for name in ("RolePermission", "UserPermission"):
        try:
            M = apps.get_model("accounts", name)
        except LookupError:
            continue
        M.objects.filter(perm__in=OLD_PERMS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0026_mtef_decisions"),
        ("accounts", "0007_role_and_user_permissions"),
    ]

    operations = [
        migrations.RunPython(drop_perms, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(name="mtefline", unique_together=set()),
        migrations.AlterUniqueTogether(name="mtefceiling", unique_together=set()),
        migrations.RemoveField(model_name="project", name="bank_project"),
        migrations.RemoveField(model_name="project", name="outside_bank_reason"),
        migrations.DeleteModel(name="MTEFLine"),
        migrations.DeleteModel(name="MTEFCeiling"),
        migrations.DeleteModel(name="MTEFPlan"),
        migrations.DeleteModel(name="BankDoc"),
        migrations.DeleteModel(name="BankProject"),
        migrations.DeleteModel(name="SectorPlanDefault"),
        migrations.DeleteModel(name="PlanProgram"),
        migrations.DeleteModel(name="PlanPillar"),
        migrations.DeleteModel(name="ScoreCriterion"),
        migrations.DeleteModel(name="ResourceHead"),
        migrations.DeleteModel(name="PlanSettings"),
    ]
