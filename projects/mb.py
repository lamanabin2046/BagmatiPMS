"""नापी किताब: परिमाण सूची (BOQ), नापी, भौतिक प्रगति र बिलको आधार.

परिमाण = संख्या × लम्बाइ × चौडाइ × उचाइ (भरिएका आयाम मात्र) — कुनै आयाम नभरे सिधै परिमाण।
घटाउ (deduction) नापी ऋणात्मक गनिन्छ।
मूल्याङ्कन = Σ (हरेक कामको नापिएको परिमाण × BOQ दर)।
भौतिक प्रगति % = मूल्याङ्कन ÷ BOQ जम्मा।
बोलपत्रको रनिङ / अन्तिम बिल: नापी किताब भए यही मूल्याङ्कन आधार (फरक राख्दा कारण चाहिन्छ);
बिल दर्ता हुँदा त्यो मितिसम्मका नबिलिएका नापीमा बिल नं. लाग्छ।
"""
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")
Q3 = Decimal("0.001")


def D(v):
    return Decimal(str(v or 0))


def num(raw):
    """'1,250.5' / '१२५' → Decimal; खाली → None; मिलेन → 'bad'."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return Decimal(str(raw).replace(",", "").strip().translate(str.maketrans("०१२३४५६७८९", "0123456789")))
    except (InvalidOperation, ValueError):
        return "bad"


def compute_qty(nos, length, breadth, height, direct):
    dims = [x for x in (nos, length, breadth, height) if x is not None]
    if dims:
        q = Decimal("1")
        for x in dims:
            q *= x
        return q.quantize(Q3)
    return direct.quantize(Q3) if direct is not None else None


def item_rows(project):
    rows = []
    for it in project.boq_items.all():
        ms = list(it.measurements.all())
        qty = sum((m.signed_quantity for m in ms), ZERO)
        billed = sum((m.signed_quantity for m in ms if m.bill_no), ZERO)
        value = (qty * D(it.rate)).quantize(Decimal("0.01"))
        rows.append({"item": it, "measurements": ms, "qty": qty, "billed_qty": billed, "value": value,
                     "amount": it.amount, "pct": round(qty * 100 / D(it.quantity), 1) if it.quantity else 0,
                     "over": qty > D(it.quantity), "excess": max(qty - D(it.quantity), ZERO)})
    return rows


def summary(project, rows=None):
    rows = item_rows(project) if rows is None else rows
    boq = sum((r["amount"] for r in rows), ZERO)
    value = sum((r["value"] for r in rows), ZERO)
    unbilled = sum(((r["qty"] - r["billed_qty"]) * D(r["item"].rate) for r in rows), ZERO).quantize(Decimal("0.01"))
    return {"has": bool(rows), "items": len(rows), "boq_total": boq, "value": value, "unbilled": unbilled,
            "progress": round(value * 100 / boq, 1) if boq else 0, "over_items": sum(1 for r in rows if r["over"]),
            "measurements": sum(len(r["measurements"]) for r in rows)}


def value_upto(project, day=None):
    """त्यो मितिसम्मको नापी अनुसारको कुल मूल्याङ्कन."""
    total = ZERO
    for it in project.boq_items.all():
        for m in it.measurements.all():
            if day is None or m.date <= day:
                total += m.signed_quantity * D(it.rate)
    return total.quantize(Decimal("0.01"))


def mark_billed(project, bill_no, day):
    from .models import Measurement

    return Measurement.objects.filter(item__project=project, bill_no__isnull=True, date__lte=day).update(bill_no=bill_no)


HEADERS = {
    "sn": ("sn", "s.n", "s.n.", "क्र.सं.", "क्र.सं", "क्रसं"),
    "description": ("description", "item", "विवरण", "कामको विवरण"),
    "unit": ("unit", "एकाइ", "इकाई"),
    "quantity": ("quantity", "qty", "परिमाण"),
    "rate": ("rate", "दर"),
}


def parse_boq(fileobj):
    """Excel → ([{sn, description, unit, quantity, rate}], errors)."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(fileobj, data_only=True, read_only=True)
    except Exception:
        return [], ["Excel (.xlsx) फाइल पढ्न सकिएन।"]
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    col, start = None, 0
    for i, r in enumerate(rows[:15]):
        names = [str(c).strip().lower() if c is not None else "" for c in r]
        found = {}
        for key, aliases in HEADERS.items():
            for j, n in enumerate(names):
                if n in aliases:
                    found[key] = j
                    break
        if {"description", "unit", "quantity", "rate"} <= set(found):
            col, start = found, i + 1
            break
    if col is None:
        return [], ["शीर्ष पङ्क्ति भेटिएन — स्तम्भ: sn, description, unit, quantity, rate (वा क्र.सं., विवरण, एकाइ, परिमाण, दर)।"]
    out, errors = [], []
    for n, r in enumerate(rows[start:], start=start + 1):
        get = lambda k: r[col[k]] if k in col and col[k] < len(r) else None  # noqa: E731
        desc = str(get("description") or "").strip()
        if not desc:
            continue
        q, rate = num(get("quantity")), num(get("rate"))
        if q in (None, "bad") or rate in (None, "bad"):
            errors.append(f"पङ्क्ति {n}: परिमाण वा दर मिलेन।")
            continue
        out.append({"sn": str(get("sn") or "").strip()[:20], "description": desc, "unit": str(get("unit") or "").strip()[:30],
                    "quantity": q, "rate": rate})
    if not out and not errors:
        errors.append("कुनै काम भेटिएन।")
    return out, errors
