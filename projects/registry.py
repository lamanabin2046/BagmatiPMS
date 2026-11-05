"""बाह्य दर्ता जाँच: IRD (PAN) विवरण र PPMO कालोसूची.

IRD PAN खोज — आधिकारिक API छैन। ird.gov.np/pan-search पेजले प्रयोग गर्ने भित्री endpoint (CSRF token लिएर
POST) बाट विवरण ल्याइन्छ। IRD ले वेबसाइट बदलेमा नचल्न सक्छ — त्यसैले:
  * सेटिङबाट खोल्ने/बन्द गर्ने (पूर्वनिर्धारित बन्द), URL मिलाउन मिल्ने
  * ८ सेकेन्ड timeout, १ दिन cache, असफल भए हातैले भर्ने
PPMO कालोसूची — blacklist.ppmo.gov.np बाट डाउनलोड/कपी गरेको सूची (Excel / CSV) आयात गरिन्छ;
  फर्म दर्ता, बोलपत्र, दरभाउपत्र र सोझै खरिदमा PAN (नभए नाम) मिलाएर आफैँ रोकिन्छ।
"""
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from datetime import date

TIMEOUT = 8
UA = "Mozilla/5.0 (PMS palika; PAN verification)"
FIELDS = {"trade_Name_Eng": "name_en", "trade_Name_Nep": "name_np", "address": "address", "account_Status": "status",
          "eff_Reg_Date": "reg_date", "office_Name": "office", "filing_Period": "filing_period", "tax_Clearance": "tax_clearance"}


class LookupError_(Exception):
    pass


def _find(obj, out):
    """JSON जुनसुकै ढाँचामा भए पनि चिनिएका field खोज्ने."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = next((FIELDS[f] for f in FIELDS if f.lower() == str(k).lower()), None)
            if key and v not in (None, "") and key not in out:
                out[key] = str(v).strip()
            elif isinstance(v, (dict, list)):
                _find(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _find(v, out)
    return out


def parse_ird(payload):
    """IRD को JSON → {name_en, name_np, address, status, ...}; नभेटिए {}."""
    if payload in (0, "0", None, "", [], {}):
        return {}
    data = _find(payload, {})
    if "vat" not in data:
        blob = json.dumps(payload, ensure_ascii=False).lower()
        data["vat"] = "vat" in blob and "not" not in blob.split("vat")[0][-20:]
    return data if (data.get("name_en") or data.get("name_np")) else {}


def lookup_pan(pan, settings):
    """IRD बाट PAN विवरण (cache सहित). असफल भए LookupError_."""
    from django.core.cache import cache

    pan = (pan or "").strip()
    if not (pan.isdigit() and len(pan) == 9):
        raise LookupError_("PAN ९ अङ्कको हुनुपर्छ।")
    if not settings.ird_lookup_enabled:
        raise LookupError_("IRD बाट विवरण ल्याउने सुविधा सेटिङमा बन्द छ।")
    key = f"ird_pan:{pan}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    try:
        page = opener.open(settings.ird_page_url, timeout=TIMEOUT).read().decode("utf-8", "ignore")
        m = re.search(r'name=["\']_token["\']\s+value=["\']([^"\']+)', page) or \
            re.search(r'value=["\']([^"\']+)["\']\s+name=["\']_token', page) or \
            re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
        token = m.group(1) if m else ""
        body = json.dumps({"_token": token, "pan": pan, "captcha": ""}).encode()
        req = urllib.request.Request(settings.ird_api_url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-CSRF-TOKEN": token,
                                              "X-Requested-With": "XMLHttpRequest", "Referer": settings.ird_page_url})
        raw = opener.open(req, timeout=TIMEOUT).read().decode("utf-8", "ignore")
    except Exception as e:  # नेटवर्क, timeout, HTTP त्रुटि
        raise LookupError_(f"IRD सँग सम्पर्क हुन सकेन ({e.__class__.__name__}) — विवरण हातैले भर्नुहोस्।")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise LookupError_("IRD को जवाफ बुझ्न सकिएन (वेबसाइट बदलिएको हुन सक्छ) — विवरण हातैले भर्नुहोस्।")
    data = parse_ird(payload)
    if not data:
        raise LookupError_(f"PAN {pan} IRD मा भेटिएन।")
    data["pan"] = pan
    cache.set(key, data, 24 * 3600)
    return data


# ---------------------------------------------------------------- PPMO कालोसूची
def norm(name):
    """नाम मिलाउन: खाली ठाउँ/चिह्न हटाई, प्रा.लि./Pvt. Ltd. जस्ता शब्द बिना."""
    s = (name or "").lower()
    for w in ("प्रा.लि.", "प्रा. लि.", "प्रालि", "pvt. ltd.", "pvt ltd", "private limited", "p. ltd.", "ltd.", "ltd",
              "कन्स्ट्रक्सन", "construction", "निर्माण सेवा", "निर्माण", "j.v.", "jv"):
        s = s.replace(w, " ")
    return re.sub(r"[\s\.\,\-\(\)/&]+", "", s)


HEADERS = {
    "name": ("name", "firm", "firm name", "name of firm", "company", "company name", "bidder", "फर्म", "फर्मको नाम",
             "कम्पनीको नाम", "संस्थाको नाम", "नाम", "निर्माण व्यवसायीको नाम"),
    "pan": ("pan", "pan no", "pan no.", "pan/vat", "vat", "registration no", "reg no", "दर्ता नं", "दर्ता नं.", "प्यान",
            "स्थायी लेखा नं", "स्थायी लेखा नं."),
    "address": ("address", "ठेगाना"),
    "from": ("from", "from date", "start date", "blacklisted from", "देखि", "कालोसूचीमा राखिएको मिति", "मिति देखि"),
    "to": ("to", "to date", "end date", "blacklisted to", "until", "सम्म", "अवधि सम्म", "मिति सम्म"),
    "reason": ("reason", "remarks", "कारण", "कैफियत"),
    "decision": ("decision", "decision date", "notice", "निर्णय", "निर्णय मिति", "सूचना"),
}


def _date(v):
    """Excel मिति, '२०८२-०१-१५' (वि.सं.) वा '2025-04-28' (इ.सं.) → date | None."""
    from datetime import datetime

    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip().translate(str.maketrans("०१२३४५६७८९", "0123456789")).replace("/", "-").replace(".", "-")
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    if y > 2050:   # वि.सं.
        from biddings.views_workflow import to_ad

        return to_ad(f"{y:04d}-{mo:02d}-{d:02d}")
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_blacklist(fileobj, filename=""):
    """Excel / CSV → ([{name, pan, address, from_date, to_date, reason, decision}], errors)."""
    rows = []
    try:
        if filename.lower().endswith(".csv"):
            import csv
            import io
            text = fileobj.read().decode("utf-8-sig", "ignore")
            rows = list(csv.reader(io.StringIO(text)))
        else:
            from openpyxl import load_workbook
            wb = load_workbook(fileobj, data_only=True, read_only=True)
            rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
    except Exception:
        return [], ["फाइल पढ्न सकिएन — Excel (.xlsx) वा CSV मात्र।"]
    col, start = None, 0
    for i, r in enumerate(rows[:15]):
        names = [str(c).strip().lower().rstrip(":") if c is not None else "" for c in r]
        found = {}
        for key, aliases in HEADERS.items():
            for j, n in enumerate(names):
                if n in aliases and j not in found.values():
                    found[key] = j
                    break
        if "name" in found:
            col, start = found, i + 1
            break
    if col is None:
        return [], ["शीर्ष पङ्क्ति भेटिएन — कम्तीमा फर्मको नाम (Name / फर्मको नाम) स्तम्भ चाहिन्छ।"]
    out = []
    for r in rows[start:]:
        get = lambda k: r[col[k]] if k in col and col[k] < len(r) else None  # noqa: E731
        name = str(get("name") or "").strip()
        if not name:
            continue
        pan = re.sub(r"\D", "", str(get("pan") or "").translate(str.maketrans("०१२३४५६७८९", "0123456789")))
        out.append({"name": name[:250], "pan": pan[:20], "address": str(get("address") or "").strip()[:250],
                    "from_date": _date(get("from")), "to_date": _date(get("to")),
                    "reason": str(get("reason") or "").strip()[:500], "decision": str(get("decision") or "").strip()[:200]})
    return out, ([] if out else ["कुनै फर्म भेटिएन।"])


def ppmo_match(firm=None, name="", pan=""):
    """PPMO कालोसूचीमा (हाल लागू) मिल्ने प्रविष्टि वा None — PAN पहिले, नभए नाम."""
    from django.db.models import Q

    from .models import PPMOBlacklist

    if firm is not None:
        name, pan = firm.firm_name, firm.firm_pan
    today = date.today()
    active = PPMOBlacklist.objects.filter(Q(to_date__isnull=True) | Q(to_date__gte=today))
    pan = (pan or "").strip()
    if pan:
        hit = active.filter(pan=pan).first()
        if hit:
            return hit
    key = norm(name)
    if not key:
        return None
    for b in active.only("id", "name", "name_key", "to_date", "decision", "reason", "pan"):
        if b.name_key == key:
            return b
    return None
