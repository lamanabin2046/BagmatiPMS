"""पुराना (SQLite बाट सारिएका) अभिलेखमा tax_deduction JSON object नभई text ('{"agrim_tax": 2.0}') भएर बसेको —
dict मा बदल्ने। बिग्रिएको text भए खाली {} राख्ने।"""
import json

from django.db import migrations


def fix(apps, schema_editor):
    for model in ("FinalPayment", "Installment"):
        M = apps.get_model("usercommittee", model)
        for obj in M.objects.all().only("id", "tax_deduction"):
            v = obj.tax_deduction
            if isinstance(v, dict):
                continue
            try:
                parsed = json.loads(v) if isinstance(v, str) and v.strip() else {}
            except ValueError:
                parsed = {}
            if not isinstance(parsed, dict):
                parsed = {}
            M.objects.filter(id=obj.id).update(tax_deduction=parsed)


class Migration(migrations.Migration):
    dependencies = [("usercommittee", "0018_public_audit")]
    operations = [migrations.RunPython(fix, migrations.RunPython.noop)]
