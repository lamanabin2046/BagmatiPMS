"""योजना Excel आयातको ढाँचा (.xlsx) — यही पालिकाको चालु आ.व., वडा, बजेट प्रकार, योजना प्रकार, क्षेत्र सहित.

"Projects" पानामा ड्रपडाउन; छानिएको मान "id | नाम" हुन्छ, आयातले अगाडिको id मात्र लिन्छ (projects/views.py: _to_id)।
"सूची" पानामा ड्रपडाउनका विकल्प। पहिलो ३ पङ्क्ति शीर्षक / नेपाली नाम / स्तम्भ नाम — आयातले स्तम्भ नामको पङ्क्ति आफैँ खोज्छ।
"""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROWS = 500   # ड्रपडाउन लाग्ने पङ्क्ति

# (स्तम्भ नाम, नेपाली शीर्षक, अनिवार्य?, चौडाइ, सूचीको key / None)
COLUMNS = [
    ("name", "योजनाको नाम", True, 42, None),
    ("address", "सञ्चालन स्थान", True, 26, None),
    ("budget", "विनियोजित बजेट (रु.)", True, 18, None),
    ("fiscalyear_id", "आर्थिक वर्ष", True, 16, "fy"),
    ("ward_id", "वडा नं.", True, 14, "ward"),
    ("budget_type_id", "बजेट व्यहोर्ने स्रोत", True, 24, "budget_type"),
    ("project_type_id", "योजनाको प्रकार", True, 22, "project_type"),
    ("sector", "क्षेत्र", False, 24, "sector"),
    ("subsector", "उपक्षेत्र", False, 26, "subsector"),
]


# नमुना पङ्क्ति (नयाँ पालिकामा सधैँ हुने नाम — tenants/provisioning.py, migration 0009)
SAMPLE = ["वडा नं. १ को बजार–स्कुल सडक कालोपत्रे", "वडा नं. १, बजार टोल", 2500000, None, "१", "स्थानीय तह", "वडा स्तरीय",
          "पूर्वाधार विकास", "सडक तथा पुल"]


SAMPLE_PREFIX = "नमुना: "


class _FY:
    def __init__(self, name):
        self.id, self.name = None, name


def build(palika_name="", generic_fy=None, sample=False):
    """generic_fy: DB नपढी सामान्य (नाममा आधारित) सूची — कुनै पनि पालिकामा अपलोड हुने फाइल; sample: नमुना पङ्क्ति थप्ने."""
    if generic_fy:
        import importlib

        from tenants.provisioning import BUDGET_TYPES, PROJECT_TYPES

        SECTORS = importlib.import_module("projects.migrations.0009_seed_sectors").DEFAULTS

        fy = _FY(generic_fy)
        np_ = str.maketrans("0123456789", "०१२३४५६७८९")
        lists = {
            "fy": [generic_fy], "ward": [str(i).translate(np_) for i in range(1, 21)],
            "budget_type": list(BUDGET_TYPES), "project_type": list(PROJECT_TYPES),
            "sector": [s for s, _subs in SECTORS], "subsector": [x for _s, subs in SECTORS for x in subs],
        }
    else:
        from accounts.models import Ward

        from .fiscal import current_fy
        from .models import Budget_Type, Project_Type, Sector, SubSector

        fy = current_fy()
        lists = {
            "fy": [f"{fy.id} | {fy.name}"] if fy else [],
            "ward": [f"{w.id} | वडा {w.name}" for w in Ward.objects.order_by("id")],
            "budget_type": [f"{b.id} | {b.name}" for b in Budget_Type.objects.order_by("id")],
            "project_type": [f"{t.id} | {t.type}" for t in Project_Type.objects.order_by("id")],
            "sector": [s.name for s in Sector.objects.order_by("name")],
            "subsector": [s.name for s in SubSector.objects.order_by("sector__name", "name")],
        }

    wb = Workbook()
    ws = wb.active
    ws.title = "Projects"
    navy, light, req = "1F2A5C", "EEF2FB", "FDE8E8"
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # १: शीर्षक, २: नेपाली नाम, ३: स्तम्भ नाम (आयातका लागि — नबदल्नुहोस्)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLUMNS))
    ws.cell(1, 1, f"{palika_name} — योजना आयात ढाँचा (आ.व. {fy.name if fy else ''})   ·   ४ औँ पङ्क्तिदेखि भर्नुहोस्; "
                  "रातो शीर्षक अनिवार्य; ड्रपडाउनबाट छान्नुहोस्; तेस्रो पङ्क्ति नबदल्नुहोस्।")
    ws.cell(1, 1).font = Font(bold=True, color="FFFFFF", size=11)
    ws.cell(1, 1).fill = PatternFill("solid", fgColor=navy)
    ws.cell(1, 1).alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 34
    for i, (key, label, required, width, _src) in enumerate(COLUMNS, start=1):
        c2 = ws.cell(2, i, label + (" *" if required else ""))
        c2.font = Font(bold=True, color="B91C1C" if required else "334155")
        c2.fill = PatternFill("solid", fgColor=req if required else light)
        c3 = ws.cell(3, i, key)
        c3.font = Font(bold=True, color="64748B", size=9)
        c3.fill = PatternFill("solid", fgColor=light)
        for c in (c2, c3):
            c.border = border
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[2].height = 30
    ws.freeze_panes = "A4"

    # सूची पाना
    ref = wb.create_sheet("सूची")
    ref.cell(1, 1, "ड्रपडाउनका विकल्प — यो पाना नबदल्नुहोस्").font = Font(bold=True, color="B91C1C")
    col_of = {}
    for j, (key, label) in enumerate([("fy", "आर्थिक वर्ष (चालु)"), ("ward", "वडा"), ("budget_type", "बजेट व्यहोर्ने स्रोत"),
                                      ("project_type", "योजनाको प्रकार"), ("sector", "क्षेत्र"), ("subsector", "उपक्षेत्र")], start=1):
        ref.cell(2, j, label).font = Font(bold=True)
        ref.column_dimensions[get_column_letter(j)].width = 30
        for r, v in enumerate(lists[key], start=3):
            ref.cell(r, j, v)
        col_of[key] = (get_column_letter(j), 2 + max(1, len(lists[key])))

    last = 3 + ROWS
    for i, (key, label, required, width, src) in enumerate(COLUMNS, start=1):
        letter = get_column_letter(i)
        if src:
            cl, end = col_of[src]
            dv = DataValidation(type="list", formula1=f"='सूची'!${cl}$3:${cl}${end}", allow_blank=True,
                                showErrorMessage=src not in ("sector", "subsector"))
            dv.error, dv.errorTitle = "सूचीबाट छान्नुहोस्।", label
            dv.prompt, dv.promptTitle = "ड्रपडाउनबाट छान्नुहोस्", label
            ws.add_data_validation(dv)
            dv.add(f"{letter}4:{letter}{last}")
        if key == "budget":
            dv = DataValidation(type="decimal", operator="greaterThan", formula1="0", allow_blank=True)
            dv.error, dv.errorTitle = "० भन्दा बढी अङ्क लेख्नुहोस्।", label
            ws.add_data_validation(dv)
            dv.add(f"{letter}4:{letter}{last}")
            for r in range(4, last + 1):
                ws.cell(r, i).number_format = "#,##0"

    if sample:
        # ४ औँ पङ्क्ति: नमुना — नाम "नमुना:" बाट सुरु हुँदा आयातले छोड्छ (projects/views.py)
        row = list(SAMPLE)
        row[0] = SAMPLE_PREFIX + row[0]
        pick = lambda key, default: next(iter(lists[key]), default)  # noqa: E731
        row[3] = pick("fy", "")
        if not generic_fy:   # यही पालिकाका सूचीबाट
            row[4], row[5], row[6] = pick("ward", ""), pick("budget_type", ""), pick("project_type", "")
            if row[7] not in lists["sector"]:
                row[7], row[8] = pick("sector", None), None
            elif row[8] not in lists["subsector"]:
                row[8] = None
        grey = Font(italic=True, color="64748B")
        for i, v in enumerate(row, start=1):
            c = ws.cell(4, i, v)
            c.font = grey
            c.fill = PatternFill("solid", fgColor="F8FAFC")

    # निर्देशन पाना
    help_ = wb.create_sheet("निर्देशन")
    help_.column_dimensions["A"].width = 110
    lines = [
        "योजना आयात — कसरी भर्ने",
        "",
        f"१. “Projects” पानाको ४ औँ पङ्क्तिदेखि एउटा योजना = एउटा पङ्क्ति। (आ.व. {fy.name if fy else ''} — चालु आ.व. मा मात्र आयात हुन्छ।)",
        "२. रातो (*) स्तम्भ अनिवार्य: योजनाको नाम, सञ्चालन स्थान, बजेट, आर्थिक वर्ष, वडा, बजेट व्यहोर्ने स्रोत, योजनाको प्रकार।",
        "३. आ.व., वडा, बजेट स्रोत, योजना प्रकार, क्षेत्र र उपक्षेत्र ड्रपडाउनबाट छान्नुहोस् (जस्तै “५ | वडा ३”) — आफैँ नलेख्नुहोस्।",
        "   ४ औँ पङ्क्ति (खैरो) नमुना हो — नाम “नमुना:” बाट सुरु भएकाले आयात हुँदैन। हेरेर त्यसैमुनि आफ्ना योजना भर्नुहोस् वा मेटाउनुहोस्।",
        "४. बजेट अङ्कमा मात्र (रु.), कमा नराखे पनि हुन्छ। नेपाली अङ्क (२५,००,०००) पनि चल्छ।",
        "५. खरिद विधि यहाँ हुँदैन — आयातपछि “वार्षिक खरिद योजना” बाट तोक्नुहोस्।",
        "६. तेस्रो पङ्क्तिका स्तम्भ नाम (name, address …) र “सूची” पाना नबदल्नुहोस्।",
        "७. भरेपछि सुरक्षित गरी “योजना अभिलेखिकरण → Excel Upload” मा अपलोड गर्नुहोस्। गल्ती भएका पङ्क्ति छुट्छन् र कारण देखिन्छ।",
        "",
        "वडा, बजेट स्रोत वा योजना प्रकार थपिएमा नयाँ ढाँचा फेरि डाउनलोड गर्नुहोस्।",
    ]
    for r, t in enumerate(lines, start=1):
        c = help_.cell(r, 1, t)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if r == 1:
            c.font = Font(bold=True, size=13, color=navy)
    wb.move_sheet("निर्देशन", offset=-1)   # Projects, निर्देशन, सूची
    wb.active = 0

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), (fy.name if fy else "")
