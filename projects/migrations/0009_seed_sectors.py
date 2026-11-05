"""पूर्वनिर्धारित क्षेत्र / उपक्षेत्र (स्थानीय तहको बजेट तर्जुमा — LMBIS अनुसार). पालिकाले सेटिङबाट थप्न/बदल्न सक्छ."""
from django.db import migrations

DEFAULTS = [
    ("आर्थिक विकास", ["कृषि", "पशुपन्छी", "सिँचाइ", "उद्योग, वाणिज्य तथा आपूर्ति", "पर्यटन", "सहकारी तथा वित्तीय क्षेत्र",
                      "भूमि व्यवस्था"]),
    ("सामाजिक विकास", ["शिक्षा", "स्वास्थ्य", "खानेपानी तथा सरसफाइ", "लैङ्गिक समानता तथा सामाजिक समावेशीकरण",
                       "युवा तथा खेलकुद", "भाषा, कला तथा संस्कृति", "सामाजिक सुरक्षा तथा संरक्षण"]),
    ("पूर्वाधार विकास", ["सडक तथा पुल", "भवन, आवास तथा शहरी विकास", "ऊर्जा (विद्युत / वैकल्पिक ऊर्जा)",
                          "सूचना तथा सञ्चार", "यातायात व्यवस्थापन", "सार्वजनिक निर्माण (अन्य)"]),
    ("वन, वातावरण तथा विपद् व्यवस्थापन", ["वन तथा भू-संरक्षण", "जलाधार संरक्षण", "वातावरण संरक्षण तथा फोहोरमैला व्यवस्थापन",
                                          "जलवायु परिवर्तन अनुकूलन", "विपद् व्यवस्थापन"]),
    ("संस्थागत विकास, सेवा प्रवाह तथा सुशासन", ["संस्थागत क्षमता विकास", "सुशासन तथा पारदर्शिता", "तथ्याङ्क तथा योजना",
                                               "न्याय तथा कानुन"]),
]


def seed(apps, schema_editor):
    Sector = apps.get_model("projects", "Sector")
    SubSector = apps.get_model("projects", "SubSector")
    if Sector.objects.exists():
        return
    for i, (name, subs) in enumerate(DEFAULTS, start=1):
        sector = Sector.objects.create(name=name, sort=i)
        for j, sub in enumerate(subs, start=1):
            SubSector.objects.create(sector=sector, name=sub, sort=j)


class Migration(migrations.Migration):
    dependencies = [("projects", "0008_sectors")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
