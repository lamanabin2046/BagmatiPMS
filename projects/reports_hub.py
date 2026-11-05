"""प्रतिवेदनहरू — सबै प्रतिवेदन एकै पेजमा (खण्ड, खोज, आ.व.).

हरेक प्रतिवेदन: (code, शीर्षक, विवरण, url name, query, icon, अनुमति, भूमिका, Excel?, आ.व.?, सर्टकट?)
अनुमति / भूमिका नमिल्ने प्रतिवेदन देखिँदैन। Excel: त्यही पेजको ?export=xlsx। छाप्ने: ?print=1 (base.html ले छाप्ने झ्याल खोल्छ)।
"""
from django.urls import NoReverseMatch, reverse

REV = ("rev.view", "rev.manage", "rev.approve", "rev.survey", "rev.collect")


def R(code, title, desc, url, icon, perms=None, roles=None, query="", xlsx=False, fy=True, star=False):
    return {"code": code, "title": title, "desc": desc, "url_name": url, "icon": icon, "perms": perms, "roles": roles,
            "query": query, "xlsx": xlsx, "fy": fy, "star": star}


SECTIONS = [
    {"key": "financial", "label": "वित्तीय प्रतिवेदन", "chip": "वित्तीय", "icon": "wallet", "tone": "blue",
     "desc": "योजनाहरूको विनियोजन, खर्च, भुक्तानी र बाँकी बजेट", "items": [
        R("FIN-01", "एकीकृत प्रतिवेदन (सबै)", "सबै खरिद विधिका योजनाको विनियोजन, खर्च र बाँकी", "uc_report_summary", "layout-dashboard",
          perms=("report.uc",), xlsx=True, star=True),
        R("FIN-02", "योजनागत वित्तीय विवरण", "हरेक योजनाको बजेट, भुक्तानी, कट्टी र बाँकी", "uc_report_projects", "table",
          perms=("report.uc",), xlsx=True),
        R("FIN-03", "समिति वित्तीय प्रतिवेदन", "उपभोक्ता समितिअनुसार भुक्तानी र जनसहभागिता योगदान",
          "palika_engineer_committee_financial_report", "chart-column", roles=("1", "8"), fy=False),
        R("FIN-04", "बजेट स्थिति", "बजेट शीर्षकअनुसार विनियोजन, खर्च र बाँकी रकम", "budget_status", "gauge",
          perms=("budget.view", "budget.manage"), xlsx=True, star=True),
    ]},
    {"key": "procurement", "label": "खरिद विधि अनुसार", "chip": "खरिद विधि", "icon": "gavel", "tone": "indigo",
     "desc": "खरिद विधिअनुसार योजनाको स्थिति, सम्झौता र भुक्तानी", "items": [
        R("PROC-01", "उपभोक्ता समिति प्रतिवेदन", "उपभोक्ता समितिबाट हुने योजनाको स्थिति र भुक्तानी", "uc_report_summary", "users",
          perms=("report.uc",), query="kind=uc", xlsx=True),
        R("PROC-02", "बोलपत्र ठेक्का प्रतिवेदन", "ठेक्का, सम्झौता, रनिङ बिल र अन्तिम भुक्तानी", "uc_report_summary", "file-text",
          perms=("report.uc",), query="kind=bid", xlsx=True),
        R("PROC-03", "दरभाउपत्र खरिद प्रतिवेदन", "सिलबन्दी दरभाउपत्रबाट भएका खरिद", "uc_report_summary", "clipboard-list",
          perms=("report.uc",), query="kind=quot", xlsx=True),
    ]},
    {"key": "tax", "label": "कर र धरौटी", "chip": "कर र धरौटी", "icon": "receipt", "tone": "amber",
     "desc": "आयकर, भ्याट, पारिश्रमिक कर र धरौटी कट्टी तथा फिर्ता", "items": [
        R("TAX-01", "कर कट्टी प्रतिवेदन", "आयकर, पारिश्रमिक कर, भ्याट कट्टी — कर शीर्षकअनुसार", "uc_report_taxes", "receipt",
          perms=("report.uc",), xlsx=True, star=True),
        R("TAX-02", "कर तथा धरौटी कट्टी विवरण", "भुक्तानीअनुसार कट्टी रजिस्टर", "deduction_register", "list-checks",
          perms=("report.uc",), xlsx=True),
        R("TAX-03", "धरौटी फिर्ता", "फिर्ता गर्न बाँकी / फिर्ता भएको धरौटी", "retention_list", "hand-coins",
          perms=("report.uc", "retention.recommend", "retention.manage")),
    ]},
    {"key": "guarantee", "label": "बैंक जमानत", "chip": "जमानत", "icon": "shield-check", "tone": "rose",
     "desc": "कार्यसम्पादन र अग्रिम भुक्तानी जमानत — म्याद र फिर्ता", "items": [
        R("BG-01", "कार्यसम्पादन जमानत (Performance Bank Guarantee)", "जमानत, म्याद सकिने मिति र फिर्ताको स्थिति",
          "performance_guarantees", "shield-check", perms=("bid.view", "quot.view"), xlsx=True),
        R("BG-02", "अग्रिम भुक्तानी जमानत (Advance Payment Guarantee)", "अग्रिम भुक्तानीको जमानत र समायोजनको स्थिति",
          "advance_guarantees", "wallet", perms=("bid.view", "quot.view"), xlsx=True),
    ]},
    {"key": "ward", "label": "वडा / पालिका स्तर", "chip": "वडा / पालिका स्तर", "icon": "building-2", "tone": "teal",
     "desc": "वडागत बजेट, प्रगति, लागत अनुमान र उपभोक्ता समिति", "items": [
        R("WARD-01", "सबै योजनाहरू (सबै वडा)", "पालिकाभरिका सबै वडाका योजनाको सूची", "palika_engineer_project_list",
          "clipboard-list", roles=("1", "8"), fy=False),
        R("WARD-02", "वडा अनुसार तुलना", "वडागत बजेट, खर्च र प्रगति तुलना", "palika_engineer_ward_comparison", "bar-chart-3",
          roles=("1", "8"), fy=False, star=True),
        R("WARD-03", "लागत अनुमान प्रतिवेदन", "स्वीकृत लागत अनुमान र सम्झौता रकम", "palika_engineer_estimated_projects", "ruler",
          roles=("1", "8"), fy=False),
        R("WARD-04", "उपभोक्ता समिति सूची", "वडाअनुसार गठन भएका उपभोक्ता समिति र पदाधिकारी", "palika_engineer_committee_list",
          "users", roles=("1", "8"), fy=False),
        R("WARD-05", "अन्तिम मूल्याङ्कन (सबै वडा)", "सबै वडाका योजनाको अन्तिम मूल्याङ्कन", "palika_engineer_final_valuations",
          "banknote", roles=("1", "8"), fy=False),
    ]},
    {"key": "physical", "label": "भौतिक प्रगति", "chip": "भौतिक प्रगति", "icon": "hard-hat", "tone": "green",
     "desc": "सडक कि.मि., भवन, खानेपानी धारा जस्ता उपलब्धि सूचक", "items": [
        R("PHY-01", "भौतिक उपलब्धि", "उपलब्धि सूचकअनुसार लक्ष्य र प्रगति", "outputs_report", "ruler",
          perms=("report.outputs",), xlsx=True),
    ]},
    {"key": "revenue", "label": "राजस्व", "chip": "राजस्व", "icon": "landmark", "tone": "emerald",
     "desc": "राजस्व ठेक्का, असुली र बाँकी", "items": [
        R("REV-01", "राजस्व प्रतिवेदन", "राजस्व ठेक्का, किस्ता असुली र बाँकी", "revenue_report", "chart-column", perms=REV, xlsx=True),
    ]},
    {"key": "audit", "label": "लेखापरीक्षण र आ.व.", "chip": "लेखापरीक्षण", "icon": "folder-archive", "tone": "slate",
     "desc": "लेखापरीक्षणका कागजात र आ.व. बन्दको सारांश", "items": [
        R("AUD-01", "लेखापरीक्षण प्याकेट", "लेखापरीक्षणका लागि सबै विवरण एकै फाइलमा (Excel)", "audit_pack", "folder-archive",
          perms=("report.uc",), xlsx=True),
        R("AUD-02", "आ.व. बन्द प्रतिवेदन", "बन्द भएको आर्थिक वर्षको सारांश", "yearend_report", "file-signature",
          perms=("yearend.close", "dashboard.view"), fy=False),
    ]},
]

TONES = {   # आइकनको पृष्ठभूमि / रङ (Tailwind)
    "blue": "bg-brand-50 text-brand-700", "indigo": "bg-indigo-50 text-indigo-700", "amber": "bg-amber-50 text-amber-700",
    "rose": "bg-rose-50 text-rose-700", "teal": "bg-teal-50 text-teal-700", "green": "bg-green-50 text-green-700",
    "emerald": "bg-emerald-50 text-emerald-700", "slate": "bg-slate-100 text-slate-700",
}
# प्रतिवेदनका पेज (साइडबारमा "प्रतिवेदनहरू" सक्रिय देखाउन)
REPORT_URL_NAMES = sorted({it["url_name"] for s in SECTIONS for it in s["items"]} | {"reports_hub", "retention_recommend",
                                                                                   "retention_release", "palika_engineer_project_detail"})


def _visible(it, t, P):
    if it["roles"] and it["perms"]:
        return t in it["roles"] or any(p in P for p in it["perms"])
    if it["roles"]:
        return t in it["roles"]
    if it["perms"]:
        return any(p in P for p in it["perms"])
    return True


def build(user, fy):
    """देखिने खण्ड र प्रतिवेदन (url, Excel / छाप्ने link सहित)।"""
    from accounts.permissions import user_perms

    from .models import FiscalYear

    P, t = user_perms(user), str(getattr(user, "user_type", ""))
    closed = FiscalYear.objects.filter(closed_at__isnull=False).order_by("-name").first()
    out = []
    for s in SECTIONS:
        items = []
        for it in s["items"]:
            if not _visible(it, t, P):
                continue
            try:
                if it["url_name"] == "yearend_report":
                    if closed is None:
                        continue
                    base = reverse("yearend_report", args=[closed.id])
                else:
                    base = reverse(it["url_name"])
            except NoReverseMatch:
                continue
            q = [it["query"]] if it["query"] else []
            if it["fy"] and fy:
                q.append(f"fiscalyear={fy.id}")
            qs = "&".join(q)
            url = base + (f"?{qs}" if qs else "")
            sep = "&" if "?" in url else "?"
            items.append(dict(it, url=url, xlsx_url=(url + sep + "export=xlsx") if it["xlsx"] else "",
                              print_url=url + sep + "print=1",
                              note=(f"आ.व. {closed.name}" if it["url_name"] == "yearend_report" and closed else "")))
        if items:
            out.append(dict(s, items=items, icon_tone=TONES[s["tone"]]))
    return out


def can_see_any(user):
    return any(build_light(user))


def build_light(user):
    from accounts.permissions import user_perms

    P, t = user_perms(user), str(getattr(user, "user_type", ""))
    return [it for s in SECTIONS for it in s["items"] if _visible(it, t, P)]
