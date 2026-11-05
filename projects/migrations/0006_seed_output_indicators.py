"""सुरुका कामको प्रकार र उपलब्धि सूचक (पालिकाले सेटिङबाट थप्न/बदल्न/निष्क्रिय गर्न मिल्छ)."""
from django.db import migrations

DEFAULTS = [
    ("सडक / बाटो", [
        ("नयाँ ट्रयाक खोलिएको (कच्ची बाटो)", "कि.मि."),
        ("ग्राभेल", "कि.मि."),
        ("कालोपत्रे", "कि.मि."),
        ("ढलान (RCC / PCC) सडक", "कि.मि."),
        ("सडक मर्मत / स्तरोन्नति", "कि.मि."),
        ("नाली निर्माण", "मिटर"),
        ("कल्भर्ट / ह्युम पाइप", "वटा"),
        ("पर्खाल (ढुङ्गा / ग्याबियन)", "घन मिटर"),
    ]),
    ("भवन", [
        ("नयाँ भवन निर्माण", "वटा"),
        ("भवन मर्मत / स्तरोन्नति", "वटा"),
        ("निर्माण क्षेत्रफल", "वर्ग मिटर"),
        ("कोठा", "वटा"),
        ("शौचालय", "वटा"),
    ]),
    ("खानेपानी", [
        ("खानेपानी योजना", "वटा"),
        ("पाइपलाइन", "मिटर"),
        ("पानी ट्याङ्की", "वटा"),
        ("धारा", "वटा"),
        ("लाभान्वित घरधुरी", "घरधुरी"),
    ]),
    ("सिँचाइ", [
        ("कुलो / नहर", "मिटर"),
        ("सिँचित क्षेत्रफल", "हेक्टर"),
    ]),
    ("पुल", [
        ("झोलुङ्गे पुल", "वटा"),
        ("मोटरेबल पुल", "मिटर"),
    ]),
    ("अन्य / साझा", [
        ("लाभान्वित जनसंख्या", "जना"),
        ("रोजगारी सिर्जना", "कार्यदिन"),
    ]),
]


def seed(apps, schema_editor):
    WorkCategory = apps.get_model("projects", "WorkCategory")
    OutputIndicator = apps.get_model("projects", "OutputIndicator")
    if WorkCategory.objects.exists():
        return
    for ci, (cat, items) in enumerate(DEFAULTS, start=1):
        c = WorkCategory.objects.create(name=cat, sort=ci * 10)
        for ii, (name, unit) in enumerate(items, start=1):
            OutputIndicator.objects.create(category=c, name=name, unit=unit, sort=ii * 10)


class Migration(migrations.Migration):
    dependencies = [("projects", "0005_physical_outputs")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
