"""खरिद प्रकारमा स्थिर कोड र नयाँ विधि (संस्था/समिति, अमानत, सोझै खरिद)."""
from django.db import migrations

BY_ID = {1: "uc", 2: "bid", 3: "quot"}          # पुराना id — कार्यप्रवाहहरूले यही id प्रयोग गर्छन्
BASE_NAMES = {1: "उपभोक्ता समिति", 2: "शिलबन्दी बोलपत्र", 3: "शिलबन्दी दरभाउ पत्र"}
NEW = [("sanstha", "संस्था / समिति मार्फत"), ("amanat", "अमानत मार्फत"), ("direct", "सोझै खरिद मार्फत")]
NOTE = ("पूर्वनिर्धारित सीमा: सार्वजनिक खरिद ऐन, २०६३ (दोस्रो संशोधन, २०८३ समेत) र सार्वजनिक खरिद नियमावली, २०६४ "
        "(चौधौँ संशोधन, २०८२ — उपभोक्ता समिति रु. १० लाख) अनुसार। कानुन संशोधन भएमा यहीँबाट मिलाउनुहोस्।")


def forward(apps, schema_editor):
    PT = apps.get_model("projects", "Procurement_Type")
    # नयाँ पालिका (खाली तालिका): पहिले १, २, ३ id कै आधारभूत विधि — नयाँ विधिले ती id नलिऊन्
    for pk, name in BASE_NAMES.items():
        if not PT.objects.filter(id=pk).exists() and not PT.objects.filter(name=name).exists():
            PT.objects.create(id=pk, name=name, code=BY_ID[pk])
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as c:
            c.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), GREATEST((SELECT MAX(id) FROM projects_procurement_type), 1))",
                      ["projects_procurement_type"])
    for pk, code in BY_ID.items():
        PT.objects.filter(id=pk, code="").update(code=code)
    for code, name in NEW:
        if not PT.objects.filter(code=code).exists():
            PT.objects.create(code=code, name=name)
    L = apps.get_model("projects", "ProcurementLimits")
    if not L.objects.exists():
        L.objects.create(note=NOTE)


class Migration(migrations.Migration):
    dependencies = [("projects", "0011_procurement_plan")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
