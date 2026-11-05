"""पत्रको ढाँचामा {{project.name}} जस्ता placeholder.

- fill(html, context)     : placeholder लाई त्यो पत्रको वास्तविक मानले बदल्ने
- catalog(context)        : यो पत्रमा प्रयोग गर्न मिल्ने placeholder र तिनको अहिलेको मान
- tokenize(html, catalog) : छापिएको पत्रका मानलाई placeholder मा फर्काउने (नयाँ ढाँचाको सुरुवात)

`{{x|np}}` ले अङ्क नेपालीमा देखाउँछ। मिति (date) आफैँ वि.सं. मा जान्छ।
सुरक्षा: Django template जस्तै — "_" बाट सुरु हुने नाम र data बदल्ने method (save, delete…) चल्दैनन्।
"""
import datetime
import re
from decimal import Decimal
from html import escape

from django.db import models
from django.template import Variable, VariableDoesNotExist

TOKEN = re.compile(r"\{\{\s*([A-Za-z][\w]*(?:\.[A-Za-z][\w]*)*)\s*(?:\|\s*(np))?\s*\}\}")
NP = str.maketrans("0123456789", "०१२३४५६७८९")

SKIP_KEYS = {"csrf_token", "request", "user", "perms", "messages", "me", "DEFAULT_MESSAGE_LEVELS", "view",
             "True", "False", "None", "today_bs", "block", "forloop"}
PALIKA_ATTRS = [
    ("full_name", "पालिकाको नाम"), ("executive_office", "कार्यालय"), ("location_line", "ठेगाना"),
    ("district", "जिल्ला"), ("province", "प्रदेश"), ("assembly", "सभा"), ("cao_name", "प्रमुख प्रशासकीय अधिकृत"),
    ("bank_name", "मुख्य बैंक"), ("phone", "फोन"), ("email", "इमेल"), ("website", "वेबसाइट"), ("slogan", "नारा"),
]
# तालिका/सूची बाहेकका सामान्य मोडेलमा देखाउने property
EXTRA_PROPS = {"deadline": "म्याद"}

# placeholder सूचीमा नेपाली नाम (नभए field को आफ्नै नाम)
OBJ_NP = {
    "project": "योजना", "usercommittee": "उपभोक्ता समिति", "user_committee": "उपभोक्ता समिति",
    "cost_estimate": "लागत अनुमान", "costestimate": "लागत अनुमान", "estimate": "लागत अनुमान",
    "final_payment": "अन्तिम भुक्तानी", "finalpayment": "अन्तिम भुक्तानी", "payment": "भुक्तानी",
    "recommendation": "वडा सिफारिस", "bid": "बोलपत्र", "bid_detail": "बोलपत्र", "contractor": "निर्माण व्यवसायी",
    "approval": "स्वीकृत",
}
FIELD_NP = {
    "name": "नाम", "address": "ठेगाना", "budget": "बजेट", "fiscalyear": "आर्थिक वर्ष", "ward": "वडा",
    "procurement_type": "खरिद प्रकार", "budget_type": "बजेट स्रोत", "project_type": "योजनाको प्रकार",
    "formation_date": "गठन मिति", "start_date": "सुरु मिति", "accomplish_date": "सम्पन्न हुने मिति",
    "extended_date": "थपिएको म्याद", "deadline": "म्याद",
    "chairman_name": "अध्यक्षको नाम", "chairman_mobile": "अध्यक्षको मोबाइल", "chairman_citizenship": "अध्यक्षको ना.प्र.नं.",
    "chairman_address": "अध्यक्षको ठेगाना", "chairman_nid": "अध्यक्षको NID",
    "secretary_name": "सचिवको नाम", "secretary_mobile": "सचिवको मोबाइल", "secretary_citizenship": "सचिवको ना.प्र.नं.",
    "treasurer_name": "कोषाध्यक्षको नाम", "treasurer_mobile": "कोषाध्यक्षको मोबाइल", "treasurer_citizenship": "कोषाध्यक्षको ना.प्र.नं.",
    "contingency_amount": "कन्टिन्जेन्सी रकम", "user_contribution": "उपभोक्ता योगदान", "total_cost": "कुल लागत",
    "final_evaluation": "अन्तिम मूल्याङ्कन रकम", "office_contribution": "कार्यालयको योगदान", "total_tax": "कुल कर कट्टी",
    "application_date": "निवेदन मिति", "letter_number": "पत्र संख्या", "chalani_number": "चलानी नं.",
    "recommendation_date": "सिफारिस मिति", "remarks": "कैफियत", "status": "अवस्था",
}
# छनोट सूची (lookup) का मान — साधारण शब्द हुने हुँदा स्वतः placeholder मा नबदल्ने
NO_AUTO = {"procurement_type", "budget_type", "project_type", "status", "palika.assembly", "palika.province"}


def _bs(d):
    try:
        from nepali.date_converter import converter

        y, m, dd = converter.english_to_nepali(d.year, d.month, d.day)
        return f"{y}-{m:02d}-{dd:02d}"
    except Exception:
        return d.isoformat()


def as_text(value):
    """placeholder को मान -> पाठ (Nepali अङ्क बाहेक)."""
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return _bs(value)
    if isinstance(value, bool):
        return "हो" if value else "होइन"
    if isinstance(value, (Decimal, float)):
        return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return str(value)


def resolve(path, context):
    if any(part.startswith("_") for part in path.split(".")):
        return ""
    try:
        return Variable(path).resolve(context)
    except (VariableDoesNotExist, Exception):
        return ""


def fill(html, context):
    def repl(m):
        text = as_text(resolve(m.group(1), context))
        if m.group(2) == "np":
            text = text.translate(NP)
        return escape(text)

    return TOKEN.sub(repl, html or "")


def _model_entries(prefix, obj, label_prefix):
    out = []
    for f in obj._meta.concrete_fields:
        if f.name in ("id", "password") or isinstance(f, (models.FileField, models.JSONField)):
            continue
        label = f"{label_prefix} — {FIELD_NP.get(f.name, str(f.verbose_name))}"
        if isinstance(f, models.ForeignKey):
            try:
                rel = getattr(obj, f.name)
            except Exception:
                rel = None
            if rel is not None:
                out.append((f"{prefix}.{f.name}", label, rel))
            continue
        out.append((f"{prefix}.{f.name}", label, getattr(obj, f.attname, None)))
    for prop, lbl in EXTRA_PROPS.items():
        if hasattr(type(obj), prop):
            try:
                out.append((f"{prefix}.{prop}", f"{label_prefix} — {lbl}", getattr(obj, prop)))
            except Exception:
                pass
    return out


def catalog(context):
    """[{token, label, value}] — यो पत्रका placeholder (अहिलेको मान सहित)."""
    flat = context.flatten() if hasattr(context, "flatten") else dict(context)
    entries = []
    palika = flat.get("palika")
    if palika is not None:
        for attr, lbl in PALIKA_ATTRS:
            entries.append((f"palika.{attr}", f"पालिका — {lbl}", getattr(palika, attr, "")))
    for key, value in flat.items():
        if not isinstance(key, str) or key.startswith("_") or key in SKIP_KEYS or key == "palika":
            continue
        if isinstance(value, models.Model):
            name = OBJ_NP.get(key) or OBJ_NP.get(value._meta.model_name) or str(value._meta.verbose_name or key)
            entries += _model_entries(key, value, name)
        elif isinstance(value, (str, int, float, Decimal, datetime.date)) and not isinstance(value, bool):
            if str(value).strip():
                entries.append((key, key, value))
    seen, out = set(), []
    for token, label, value in entries:
        text = as_text(value)
        if token in seen or not text.strip():
            continue
        seen.add(token)
        auto = token not in NO_AUTO and token.rsplit(".", 1)[-1] not in NO_AUTO
        out.append({"token": token, "label": label, "value": text[:120], "np": any(c.isdigit() for c in text),
                    "auto": auto})
    return out


def tokenize(html, items):
    """छापिएको पाठमा भएका मानलाई placeholder ले बदल्ने (लामो मान पहिले)."""
    pairs = []
    for it in items:
        if not it.get("auto", True):
            continue
        v = it["value"]
        if len(v) < 3 or v.isdigit() and len(v) < 4:
            continue
        pairs.append((escape(v, quote=False), "{{" + it["token"] + "}}"))
        nv = v.translate(NP)
        if nv != v:
            pairs.append((escape(nv, quote=False), "{{" + it["token"] + "|np}}"))
    pairs.sort(key=lambda p: -len(p[0]))
    # html tag भित्र नछोई, पाठमा मात्र
    parts = re.split(r"(<[^>]+>)", html or "")
    done = set()
    for i, part in enumerate(parts):
        if part.startswith("<"):
            continue
        for val, tok in pairs:
            if val in part and val not in done:
                part = part.replace(val, tok)
        parts[i] = part
    return "".join(parts)
