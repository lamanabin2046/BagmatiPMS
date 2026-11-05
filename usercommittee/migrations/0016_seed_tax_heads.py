from django.db import migrations

DEFAULTS = [
    ("agrim_tax", "अग्रिम कर कट्टी"),
    ("bahal_tax", "भर्पाइमा हुने बहाल कर"),
    ("dhuwani_tax", "ढुवानीमा हुने बहाल कर"),
    ("sasu_tax", "सामाजिक सुरक्षा कर"),
]


def seed(apps, schema_editor):
    TaxHead = apps.get_model("usercommittee", "TaxHead")
    for i, (code, name) in enumerate(DEFAULTS, start=1):
        TaxHead.objects.get_or_create(code=code, defaults={"name": name, "sort": i})


class Migration(migrations.Migration):
    dependencies = [("usercommittee", "0015_tax_heads")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
