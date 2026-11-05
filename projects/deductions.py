"""कर तथा धरौटी कट्टी — हरेक कट्टीको पङ्क्ति (मिति, योजना, पक्ष, स्रोत, शीर्षक, रकम) र धरौटी फिर्ताको स्थिति.

स्रोत:
    उपभोक्ता समिति  — किस्ता (Installment.tax_deduction) र अन्तिम भुक्तानी (FinalPayment.tax_deduction): {code: रकम}
    बोलपत्र ठेक्का   — रनिङ बिल र अन्तिम भुक्तानी: अग्रिम आयकर, भ्याट, धरौटी, बहाल कर (निश्चित field)
    दरभाउपत्र खरिद  — अन्तिम बिल: आयकर कट्टी, धरौटी (रिटेन्सन)

धरौटी: code "dharauti", वा उपभोक्ता समितिको कर शीर्षक जसको code/नाममा "dharauti"/"धरौटी"/"retention" छ।
"""
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")
KINDS = {"uc": "उपभोक्ता समिति", "bid": "बोलपत्र ठेक्का", "quot": "दरभाउपत्र खरिद", "direct": "सोझै खरिद",
         "amanat": "अमानत", "sanstha": "संस्था / समिति"}
PARTY_LABEL = {"uc": "उपभोक्ता समिति", "bid": "निर्माण व्यवसायी", "quot": "फर्म", "direct": "आपूर्तिकर्ता",
               "amanat": "जिम्मेवार कर्मचारी", "sanstha": "संस्था / समिति"}
MINOR = ("direct", "amanat", "sanstha")
KIND_PTYPE = {"uc": 1, "bid": 2, "quot": 3}
RETENTION = "dharauti"


def D(v):
    return Decimal(str(v or 0))


def labels():
    from usercommittee.reports import EXTRA_LABELS
    from usercommittee.tax import tax_labels

    return {**EXTRA_LABELS, **tax_labels()}


def is_retention(code, label=""):
    c, n = (code or "").lower(), label or ""
    return c == RETENTION or "dharauti" in c or "retention" in c or "धरौटी" in n


def _as_dict(v):
    from usercommittee.reports import as_dict

    return as_dict(v)


def _line(p, kind, party, d, source, code, amount, lab):
    return {"date": d, "p": p, "kind": kind, "kind_label": KINDS[kind], "party": party or "", "source": source,
            "code": code, "label": lab.get(code, code), "amount": D(amount),
            "retention": is_retention(code, lab.get(code, ""))}


def project_lines(p, kind, lab=None):
    """एउटा योजनाका सबै कट्टी पङ्क्ति (रकम ० भएका बाहेक)."""
    lab = lab or labels()
    out = []
    if kind == "uc":
        uc = getattr(p, "user_committee", None)
        party = uc.name if uc else ""
        for i in p.installments.all():
            for code, v in _as_dict(i.tax_deduction).items():
                if D(v):
                    out.append(_line(p, kind, party, i.date, f"किस्ता नं. {i.number}", code, v, lab))
        fin = getattr(p, "final_payment", None)
        if fin is not None:
            for code, v in _as_dict(fin.tax_deduction).items():
                if D(v):
                    out.append(_line(p, kind, party, fin.application_date, "अन्तिम भुक्तानी", code, v, lab))
    elif kind == "bid":
        from biddings.workflow import contract_parts, current_bid
        from usercommittee.reports import BID_TAX

        bid = current_bid(p)
        party = bid.bidder_name_nepali if bid else ""
        _c, _b, _r, fin, _adv, runs = contract_parts(bid)
        for n, r in enumerate(runs, start=1):
            for field, code in BID_TAX:
                if D(getattr(r, field, 0)):
                    out.append(_line(p, kind, party, r.evaluation_date, f"रनिङ बिल नं. {n}", code, getattr(r, field), lab))
        if fin is not None:
            for field, code in BID_TAX:
                if D(getattr(fin, field, 0)):
                    out.append(_line(p, kind, party, fin.payment_date, "अन्तिम भुक्तानी", code, getattr(fin, field), lab))
    elif kind == "quot":
        from quatation.workflow import current_quation, final_of, lowest

        q = current_quation(p)
        fin = final_of(q)
        appr = getattr(q, "approval", None) if q else None
        party = (appr.firm_name if appr and appr.firm_name else lowest(q)[0]) if q else ""
        if fin is not None:
            for code, v in (("agrim_tax", fin.taxdeduction), (RETENTION, fin.retension)):
                if D(v):
                    out.append(_line(p, kind, party, fin.application_date, "अन्तिम बिल", code, v, lab))
    elif kind in MINOR:
        from . import minor as mn

        m = mn.minor_of(p)
        party = (m.selected.name if m and m.selected else (m.in_charge if m else "")) or ""
        for n, pay in enumerate(m.payments.all() if m else [], start=1):
            src = "अन्तिम भुक्तानी" if pay.kind == "final" else f"{pay.get_kind_display()} नं. {n}"
            for code, v in (pay.taxes or {}).items():
                if D(v):
                    out.append(_line(p, kind, party, pay.date, src, code, v, lab))
    return out


def completion_date(p, kind):
    """धरौटी अवधि गन्ने मिति: अन्तिम भुक्तानी / अन्तिम बिल मिति."""
    if kind == "uc":
        fin = getattr(p, "final_payment", None)
        return fin.application_date if fin else None
    if kind == "bid":
        from biddings.workflow import contract_parts, current_bid

        fin = contract_parts(current_bid(p))[3]
        return fin.payment_date if fin else None
    if kind in MINOR:
        from . import minor as mn

        fin = mn.final_payment(mn.minor_of(p))
        return fin.date if fin else None
    from quatation.workflow import current_quation, final_of

    fin = final_of(current_quation(p))
    return fin.application_date if fin else None


def projects_qs(kind):
    """विधिअनुसार योजना queryset (कट्टी पढ्न चाहिने सम्बन्ध सहित)."""
    if kind == "uc":
        from usercommittee.workflow import workflow_queryset
    elif kind == "bid":
        from biddings.workflow import workflow_queryset
    elif kind in MINOR:
        from .minor import workflow_queryset

        return workflow_queryset().filter(procurement_type__code=kind)
    else:
        from quatation.workflow import workflow_queryset
    return workflow_queryset()


def all_lines(project_ids, kind="", code=""):
    lab = labels()
    out = []
    for k in KINDS:
        if kind and k != kind:
            continue
        for p in projects_qs(k).filter(id__in=project_ids):
            out += [ln for ln in project_lines(p, k, lab) if not code or ln["code"] == code]
    out.sort(key=lambda x: (x["date"] or date.min, x["p"].name))
    return out


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    import calendar

    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def retention_months():
    from django.db import connection

    return getattr(getattr(connection, "tenant", None), "retention_months", None) or 12


STATUS = {
    "running": "काम चालु (धरौटी कट्दै)",
    "held": "रोक्का (अवधि बाँकी)",
    "due": "फिर्ता योग्य — सिफारिस बाँकी",
    "recommended": "सिफारिस आएको — टिप्पणी बाँकी",
    "tippani": "टिप्पणी भएको — फिर्ता बाँकी",
    "released": "फिर्ता भइसकेको",
}


def retention_item(p, kind, lab=None, months=None):
    """एउटा योजनाको धरौटी: रकम, अवधि, सिफारिस/टिप्पणी/फिर्ता स्थिति. धरौटी नभए None."""
    lines = [ln for ln in project_lines(p, kind, lab) if ln["retention"]]
    held = sum((ln["amount"] for ln in lines), ZERO)
    if not held:
        return None
    months = retention_months() if months is None else months
    done = completion_date(p, kind)
    due = add_months(done, months) if done else None
    rel = getattr(p, "retention_release", None)   # नभए None (RelatedObjectDoesNotExist ⊂ AttributeError)
    today = date.today()
    if rel is not None and rel.released_on:
        st = "released"
    elif rel is not None and rel.tippani_printed_at:
        st = "tippani"
    elif rel is not None:
        st = "recommended"
    elif not done:
        st = "running"
    elif due and due > today:
        st = "held"
    else:
        st = "due"
    return {"p": p, "kind": kind, "kind_label": KINDS[kind], "party": lines[0]["party"],
            "party_label": PARTY_LABEL[kind], "lines": lines, "held": held, "completed_on": done, "due": due,
            "days_left": (due - today).days if due else None, "release": rel, "status": st, "status_label": STATUS[st]}


def retention_items(project_ids, kind=""):
    lab, months = labels(), retention_months()
    out = []
    for k in KINDS:
        if kind and k != kind:
            continue
        qs = projects_qs(k).filter(id__in=project_ids).select_related("retention_release")
        for p in qs:
            item = retention_item(p, k, lab, months)
            if item:
                out.append(item)
    return out


def kind_of(project):
    code = getattr(getattr(project, "procurement_type", None), "code", "")
    return code if code in KINDS else None
