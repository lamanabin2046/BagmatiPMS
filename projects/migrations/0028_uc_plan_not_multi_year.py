"""उपभोक्ता समिति मार्फतको खरिद योजना बहुवर्षीय हुँदैन — पहिले टिक लागेका भए हटाउने."""
from django.db import migrations


def clear(apps, schema_editor):
    apps.get_model("projects", "ProcurementPlan").objects.filter(method="uc", multi_year=True).update(multi_year=False)


class Migration(migrations.Migration):

    dependencies = [("projects", "0027_remove_project_bank_mtef")]

    operations = [migrations.RunPython(clear, migrations.RunPython.noop)]
