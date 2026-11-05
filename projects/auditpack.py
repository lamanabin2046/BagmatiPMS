"""लेखापरीक्षण प्याकेट — एक आ.व. को लेखापरीक्षणमा माग हुने सबै विवरण एउटै Excel (धेरै पाना) मा.

पाना: सारांश · योजना र भुक्तानी · कर तथा कट्टी · धरौटी · बैंक जमानत · बजेट शीर्षक · राजस्व ठेक्का ·
       राजस्व असुली (रसिद) · आ.व. बन्द · गतिविधि लग
हिसाब प्रतिवेदनकै (usercommittee.reports, projects.deductions, projects.views_guarantees) — अङ्क मिल्छन्।
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

ZERO = Decimal("0")


def fy_range(fy):
    """'2083/84' → (२०८३ साउन १, २०८४ असार मसान्त) इ.सं. मा; नमिले (None, None)."""
    from biddings.views_workflow import to_ad

    try:
        y = int(fy.name.split("/")[0].translate(str.maketrans("०१२३४५६७८९", "0123456789")))
        start, nxt = to_ad(f"{y}-04-01"), to_ad(f"{y + 1}-04-01")
        return (start, nxt - timedelta(days=1)) if start and nxt else (None, None)
    except Exception:
        return None, None


def _f(v):
    return float(v) if v is not None else None


def build(fy, wards=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from usercommittee.models import ActivityLog
    from usercommittee.reports import all_rows
    from usercommittee.workflow import bs_date

    from . import dashboard as dbm
    from . import revenue as rv
    from .budget import distributed, usage
    from .deductions import all_lines, retention_items
    from .models import BudgetHead, Project, RevenuePayment, YearEndLine
    from .views_guarantees import apg_rows, pg_rows

    projects = Project.objects.filter(fiscalyear=fy)
    if wards is not None:
        projects = projects.filter(ward_id__in=wards)
    ids = list(projects.values_list("id", flat=True))
    idset = set(ids)
    wb = Workbook()
    head_fill, bold = PatternFill("solid", fgColor="E8EEFB"), Font(bold=True)

    def sheet(title, header, rows, widths=None, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title[:31]
        ws.append([f"{title} — आ.व. {fy.name}"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append(header)
        for c in ws[2]:
            c.font, c.fill = bold, head_fill
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths or [], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A3"
        return ws

    # १. सारांश
    d = dbm._compute(fy, wards)
    start, end = fy_range(fy)
    summary = [["योजना संख्या", d["count"]], ["विनियोजित बजेट", _f(d["allocated"])], ["यस आ.व. को खर्च", _f(d["spent"])],
               ["प्रतिबद्धता (सम्झौता / लागत अनुमान)", _f(d["committed"])], ["बाँकी बजेट", _f(d["remaining"])],
               ["खर्च %", _f(d["spent_pct"])], ["क्रमागत योजना", d["carried"]], ["विधि नतोकिएका योजना", d["unassigned"]]]
    summary += [[f"स्थिति: {s['label']}", s["n"]] for s in d["status"].values()]
    summary += [[f"विधि: {m['label']}", m["n"], _f(m["allocated"]), _f(m["spent"])] for m in d["methods"]]
    r = d["revenue"]
    summary += [["राजस्व स्रोत", r["n"]], ["राजस्व सम्झौता", _f(r["contract"])], ["राजस्व असुल", _f(r["collected"])],
                ["राजस्व बाँकी", _f(r["outstanding"])], ["राजस्व बक्यौता", _f(r["arrears"])],
                ["फिर्ता बाँकी धरौटी", _f(d["retention"]["held"])],
                ["आ.व. अवधि", f"{bs_date(start)} – {bs_date(end)}" if start else ""],
                ["आ.व. स्थिति", f"बन्द ({fy.close_ref})" if fy.closed_at else "खुला"],
                ["तयार गरेको मिति", bs_date(date.today())]]
    sheet("सारांश", ["विवरण", "संख्या / रकम", "विनियोजित", "खर्च"], summary, [42, 18, 16, 16], first=True)

    # २. योजना र भुक्तानी
    rows = all_rows(ids)
    before = dict(projects.values_list("id", "spent_before"))
    sheet("योजना र भुक्तानी",
          ["क्र.सं.", "वडा", "योजना", "विधि", "पक्ष (समिति / फर्म)", "विनियोजित", "सम्झौता / लागत अनुमान", "कुल भुक्तानी",
           "कर / कट्टी", "खुद भुक्तानी", "अघिल्ला आ.व. मा", "बाँकी", "स्थिति"],
          [[i, r["p"].ward.name if r["p"].ward else "", r["p"].name, r["kind_label"], r.get("party", ""), _f(r["allocated"]),
            _f(r.get("contract")), _f(r["gross"]), _f(r["tax"]), _f(r["net"]), _f(before.get(r["p"].id) or 0),
            _f(r["remaining"]), r["status_label"]] for i, r in enumerate(rows, 1)],
          [6, 6, 40, 16, 28, 14, 16, 14, 12, 14, 14, 14, 18])

    # ३. कर तथा कट्टी
    lines = all_lines(ids)
    sheet("कर तथा कट्टी", ["क्र.सं.", "मिति", "योजना", "विधि", "पक्ष", "कट्टी शीर्षक", "रकम", "स्रोत"],
          [[i, bs_date(ln["date"]), ln["p"].name, ln["kind_label"], ln["party"], ln["label"], _f(ln["amount"]), ln["source"]]
           for i, ln in enumerate(lines, 1)], [6, 12, 40, 16, 28, 30, 14, 20])

    # ४. धरौटी
    ret = retention_items(ids)
    sheet("धरौटी", ["क्र.सं.", "योजना", "विधि", "पक्ष", "रोक्का धरौटी", "सम्पन्न मिति", "फिर्ता योग्य मिति", "स्थिति",
                    "फिर्ता मिति", "फिर्ता रकम", "भौचर"],
          [[i, x["p"].name, x["kind_label"], x["party"], _f(x["held"]), bs_date(x["completed_on"]), bs_date(x["due"]),
            x["status_label"], bs_date(x["release"].released_on) if x["release"] else "",
            _f(x["release"].released_amount) if x["release"] else None, x["release"].voucher_number if x["release"] else ""]
           for i, x in enumerate(ret, 1)], [6, 40, 16, 28, 14, 12, 14, 26, 12, 14, 14])

    # ५. बैंक जमानत
    g = [(x, "कार्यसम्पादन") for x in pg_rows() if x["p"].id in idset] + \
        [(x, "अग्रिम भुक्तानी") for x in apg_rows() if x["p"].id in idset]
    sheet("बैंक जमानत", ["क्र.सं.", "योजना", "विधि", "जमानत", "पक्ष", "बैंक", "नम्बर", "रकम", "जारी", "म्याद", "स्थिति"],
          [[i, x["p"].name, x["kind_label"], kind, x["party"], x["bank"], x["number"], _f(x["amount"]), x["issue_bs"],
            x["expiry_bs"], x["status_label"]] for i, (x, kind) in enumerate(g, 1)],
          [6, 40, 14, 14, 28, 22, 18, 14, 12, 12, 18])

    # ६. बजेट शीर्षक
    heads = list(BudgetHead.objects.filter(fiscalyear=fy).select_related("budget_type"))
    hrows = []
    for i, h in enumerate(heads, 1):
        pids = list(Project.objects.filter(budget_head=h).values_list("id", flat=True))
        u = usage(pids)
        hrows.append([i, h.code, h.name, str(h.budget_type) if h.budget_type else "", _f(h.allocated), _f(distributed(h)),
                      _f(sum((x["spent"] for x in u.values()), ZERO)), len(pids)])
    sheet("बजेट शीर्षक", ["क्र.सं.", "उपशीर्षक नं.", "शीर्षक / कार्यक्रम", "बजेट प्रकार", "स्वीकृत", "योजनामा बाँडिएको",
                         "खर्च", "योजना संख्या"], hrows, [6, 14, 40, 18, 16, 16, 16, 10])

    # ७. राजस्व ठेक्का र ८. असुली
    src = rv.queryset().filter(fiscalyear=fy)
    if wards is not None:
        src = src.filter(ward_id__in=wards)
    srows = []
    for i, s in enumerate(src, 1):
        ms = rv.money_status(s)
        srows.append([i, s.name, s.get_category_display(), s.ward.name if s.ward else "", s.selected.name if s.selected else "",
                      _f(s.est_revenue), _f(s.min_bid), _f(s.contract_amount), bs_date(s.agreement_date),
                      f"{bs_date(s.start_date)} – {bs_date(s.end_date)}" if s.start_date else "", _f(ms["paid"]),
                      _f(ms["late_paid"]), _f(ms["penalty"]), _f(ms["outstanding"]), _f(s.arrears), s.get_status_display()])
    sheet("राजस्व ठेक्का", ["क्र.सं.", "स्रोत", "प्रकार", "वडा", "ठेकेदार", "अनुमानित", "न्यूनतम कबोल", "सम्झौता", "सम्झौता मिति",
                           "अवधि", "असुल", "विलम्ब शुल्क", "जरिवाना", "बाँकी", "बक्यौता", "स्थिति"], srows,
          [6, 34, 20, 6, 26, 14, 14, 14, 12, 24, 14, 12, 12, 14, 12, 12])
    pays = RevenuePayment.objects.filter(instalment__source__in=src).select_related("instalment__source__selected")
    sheet("राजस्व असुली", ["क्र.सं.", "रसिद नं.", "मिति", "स्रोत", "ठेकेदार", "किस्ता", "रकम", "विलम्ब शुल्क", "SuTRA"],
          [[i, p.receipt_no, bs_date(p.date), p.instalment.source.name,
            p.instalment.source.selected.name if p.instalment.source.selected else "", p.instalment.n, _f(p.amount),
            _f(p.late_fee), "मिलेको" if p.sutra_ok else ("मिलेन" if p.sutra_checked_at else "जाँच बाँकी")]
           for i, p in enumerate(pays, 1)], [6, 14, 12, 34, 26, 8, 14, 12, 12])

    # ९. आ.व. बन्द
    ye = YearEndLine.objects.filter(fiscalyear=fy).select_related("to_fiscalyear")
    sheet("आ.व. बन्द", ["क्र.सं.", "योजना", "वडा", "विधि", "स्थिति", "निर्णय", "विनियोजित", "खर्च", "नयाँ आवंटन", "सारिएको आ.व.", "धरौटी"],
          [[i, x.project_name, x.ward_name, x.kind_label, x.status_label, x.get_action_display(), _f(x.allocated), _f(x.spent),
            _f(x.new_allocation), x.to_fiscalyear.name if x.to_fiscalyear else "", _f(x.retention_held)]
           for i, x in enumerate(ye, 1)], [6, 40, 6, 16, 18, 30, 14, 14, 14, 12, 12])

    # १०. गतिविधि लग (आ.व. अवधिभित्र)
    logs = ActivityLog.objects.select_related("user").order_by("created_at")
    if start:
        from django.utils import timezone
        tz = timezone.get_current_timezone()
        logs = logs.filter(created_at__gte=datetime.combine(start, time.min, tz), created_at__lte=datetime.combine(end, time.max, tz))
    sheet("गतिविधि लग", ["क्र.सं.", "समय", "प्रयोगकर्ता", "कार्य", "किसिम", "विवरण", "योजना", "टिप्पणी"],
          [[i, timezone_str(x.created_at), str(x.user) if x.user else "", x.get_action_display(), x.model_name, x.object_repr,
            x.project_name or "", x.note] for i, x in enumerate(logs[:20000], 1)], [6, 18, 18, 12, 18, 40, 34, 40])
    return wb


def timezone_str(dt):
    from django.utils import timezone

    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else ""
