"""सोझै खरिद / अमानत / संस्था-समिति मार्फतको खरिद — चरण, स्थिति र कानुनी जाँच.

चरण:
  सोझै खरिद (ऐन दफा ४१)   : खरिद योजना → लागत अनुमान → दरभाउ (कम्तीमा ३) → छनौट स्वीकृति → खरिद आदेश
                            → आपूर्ति र जाँचपास → भुक्तानी
  संस्था / समिति (दफा ४६)  : खरिद योजना → लागत अनुमान → सूचना / आशयपत्र → प्रस्ताव → छनौट स्वीकृति → सम्झौता
                            → (किस्ता) → काम सम्पन्न प्रतिवेदन → अन्तिम भुक्तानी
  अमानत (दफा ४५)          : खरिद योजना → लागत अनुमान → स्वीकृति → कार्यादेश → हाजिरी / सामग्री बिल
                            → नापजाँच (मूल्याङ्कन) → फरफारक / अन्तिम भुक्तानी

नियम (सर्भरमा):
  * खरिद योजना स्वीकृत नभई लागत अनुमान दर्ता गर्न नमिल्ने (पालिकाको सेटिङ खुला भए)
  * सोझै खरिद: लागत अनुमान सोझै खरिद सीमाभित्र; कम्तीमा ३ दरभाउ; छानिएको दरभाउ लागत अनुमानभित्र
  * संस्था / समिति: सूचना कम्तीमा १५ दिन (सीमाभन्दा बढीमा खुला आशयपत्र)
  * हरेक भुक्तानीपछि कुल खर्च विनियोजित बजेटभित्र (projects/budget.py); आदेश / जाँचपास रकमभन्दा बढी भुक्तानी नहुने
"""
from collections import OrderedDict
from decimal import Decimal

ZERO = Decimal("0")
TOL = Decimal("1")
METHOD_LABEL = {"direct": "सोझै खरिद", "amanat": "अमानत", "sanstha": "संस्था / समिति"}
MIN_QUOTES = {"direct": 3, "sanstha": 1}
SANSTHA_NOTICE_DAYS = 15
TAX_FIELDS = [("agrim_tax", "अग्रिम आयकर / TDS"), ("vat", "भ्याट कट्टी"), ("dharauti", "धरौटी")]

STEPS = {
    "direct": ["plan", "estimate", "quotes", "approval", "order", "completion", "payment"],
    "sanstha": ["plan", "estimate", "notice", "quotes", "approval", "order", "progress", "completion", "payment"],
    "amanat": ["plan", "estimate", "approval", "order", "progress", "completion", "payment"],
}
LABELS = {
    "plan": ("योजना", "वार्षिक खरिद योजना स्वीकृत"),
    "estimate": ("लागत", "लागत अनुमान"),
    "notice": ("सूचना", "सूचना / आशयपत्र आह्वान"),
    "quotes": {"direct": ("दरभाउ", "दरभाउ संकलन (कम्तीमा ३)"), "sanstha": ("प्रस्ताव", "प्रस्ताव प्राप्ति")},
    "approval": {"direct": ("स्वीकृत", "दरभाउ छनौट स्वीकृति"), "sanstha": ("स्वीकृत", "संस्था छनौट स्वीकृति"),
                 "amanat": ("स्वीकृत", "अमानतबाट गर्ने स्वीकृति")},
    "order": {"direct": ("आदेश", "खरिद आदेश"), "sanstha": ("सम्झौता", "सम्झौता"), "amanat": ("कार्यादेश", "कार्यादेश")},
    "progress": {"sanstha": ("किस्ता", "किस्ता भुक्तानी (ऐच्छिक)"), "amanat": ("हाजिरी", "हाजिरी / सामग्री बिल")},
    "completion": {"direct": ("जाँचपास", "आपूर्ति र जाँचपास"), "sanstha": ("प्रतिवेदन", "काम सम्पन्न प्रतिवेदन"),
                   "amanat": ("नापजाँच", "नापजाँच / मूल्याङ्कन")},
    "payment": {"direct": ("भुक्तानी", "भुक्तानी"), "sanstha": ("भुक्तानी", "अन्तिम भुक्तानी"),
                "amanat": ("फरफारक", "अन्तिम भुक्तानी / फरफारक")},
}
STEP_PERMS = {"estimate": "minor.manage", "notice": "minor.manage", "quotes": "minor.manage", "approval": "minor.approve",
              "order": "minor.manage", "progress": "minor.manage", "completion": "minor.manage", "payment": "minor.manage"}


def D(v):
    return Decimal(str(v or 0))


def _rs(v, dec=0):
    from .templatetags.outputs import money

    return f"रु. {money(D(v), dec)}"


def _n(v):
    from .templatetags.outputs import npn

    return npn(v)


def label(key, method, short=False):
    v = LABELS[key]
    if isinstance(v, dict):
        v = v[method]
    return v[0] if short else v[1]


def columns(method):
    return [(k, label(k, method, True), label(k, method)) for k in STEPS[method]]


def method_of(project):
    from .procurement import code_of

    c = code_of(project)
    return c if c in STEPS else ""


def minor_of(project):
    return getattr(project, "minor", None)


def paid(m, exclude_final=False):
    if m is None:
        return ZERO
    return sum((D(p.gross) for p in m.payments.all() if not (exclude_final and p.kind == "final")), ZERO)


def final_payment(m):
    return next((p for p in m.payments.all() if p.kind == "final"), None) if m else None


def workflow(project):
    """(steps, summary) — steps: [{key, short, label, state, note}] state: done|current|pending|optional."""
    from .procurement import plan_gate

    method = method_of(project)
    m = minor_of(project)
    quotes = list(m.quotes.all()) if m else []
    pays = list(m.payments.all()) if m else []
    fin = next((p for p in pays if p.kind == "final"), None)
    gate = plan_gate(project) if m is None else ""
    done = {
        "plan": not gate,
        "estimate": m is not None,
        "notice": bool(m and m.notice_date),
        "quotes": len(quotes) >= MIN_QUOTES.get(method, 1),
        "approval": bool(m and m.approved_at),
        "order": bool(m and m.order_date),
        "progress": any(p.kind != "final" for p in pays),
        "completion": bool(m and m.completed_on),
        "payment": fin is not None,
    }
    notes = {
        "plan": gate or "स्वीकृत",
        "estimate": _rs(m.estimate_amount) if m else "",
        "notice": (m.notice_ref or "") if m else "",
        "quotes": f"{_n(len(quotes))} वटा" + (f" · न्यूनतम {_rs(quotes[0].amount)}" if quotes else ""),
        "approval": (f"{m.selected.name} · " if m and m.selected else "") + (m.approver_name if m and m.approved_at else ""),
        "order": (f"नं. {m.order_no} · {_rs(m.order_amount)}" if m and m.order_date else ""),
        "progress": f"{_n(sum(1 for p in pays if p.kind != 'final'))} बिल · {_rs(paid(m, True))}" if m else "",
        "completion": _rs(m.completion_value) if m and m.completed_on else "",
        "payment": f"खुद {_rs(fin.net)}" if fin else "",
    }
    steps, current = [], None
    for key in STEPS.get(method, []):
        if key == "progress":
            state = "done" if done[key] else "optional"
            if fin is None and done["order"] and not done["completion"] and current is None and method == "amanat" and not done[key]:
                state, current = "current", key
        elif done[key]:
            state = "done"
        elif current is None:
            state, current = "current", key
        else:
            state = "pending"
        steps.append({"key": key, "short": label(key, method, True), "label": label(key, method), "state": state,
                      "note": notes.get(key, "")})
    overdue = bool(m and m.due_date and not m.completed_on and m.due_date < __import__("datetime").date.today())
    return steps, {"current_key": current or "", "current_label": label(current, method) if current else "",
                   "completed": fin is not None, "overdue": overdue, "method": method, "gate": gate}


# ---------------------------------------------------------------- जाँच
def check_estimate(project, plan, amount, L):
    from .procurement import rs

    errors = []
    method = method_of(project)
    if amount is None or amount <= 0:
        return ["लागत अनुमान रकम ० भन्दा बढी हुनुपर्छ।"]
    if method == "direct":
        cap = L.consult_direct_limit if plan is not None and plan.nature == "consulting" else L.direct_limit
        if amount > D(cap) + TOL:
            errors.append(f"सोझै खरिद {rs(cap)} सम्म मात्र (ऐन दफा ४१) — यसभन्दा बढी भए वार्षिक खरिद योजनामा विधि बदल्नुहोस्।")
    budget = D(project.budget)
    if budget > 0 and amount > budget + TOL and not (plan is not None and plan.multi_year):
        errors.append(f"लागत अनुमान विनियोजित बजेट {rs(budget)} भन्दा बढी भयो।")
    return errors


def check_selection(m, quote):
    errors = []
    n = m.quotes.count()
    need = MIN_QUOTES.get(m.method, 0)
    if m.method in MIN_QUOTES:
        if n < need:
            errors.append(f"कम्तीमा {need} वटा {'दरभाउ' if m.method == 'direct' else 'प्रस्ताव'} चाहिन्छ (अहिले {n})।")
        if quote is None:
            errors.append("छनौट हुने फर्म / संस्था छान्नुहोस्।")
        elif D(quote.amount) > D(m.estimate_amount) + TOL:
            errors.append("छानिएको रकम लागत अनुमानभन्दा बढी छ — लागत अनुमानभित्रको मात्र स्वीकृत गर्न मिल्छ।")
    if m.method == "sanstha" and m.notice_date:
        from datetime import date
        days = (date.today() - m.notice_date).days
        if days < SANSTHA_NOTICE_DAYS:
            errors.append(f"सूचना प्रकाशनको {SANSTHA_NOTICE_DAYS} दिन पुगेको छैन ({days} दिन मात्र)।")
    return errors


def payment_cap(m):
    """भुक्तानीको माथिल्लो सीमा: जाँचपास रकम (भए), नत्र आदेश रकम, नत्र लागत अनुमान."""
    if m.completion_value:
        return D(m.completion_value)
    if m.order_amount:
        return D(m.order_amount)
    return D(m.estimate_amount)


def tax_total(taxes):
    return sum((D(v) for v in (taxes or {}).values()), ZERO)


def workflow_queryset():
    from .models import Project

    return (Project.objects.filter(procurement_type__code__in=list(STEPS))
            .select_related("ward", "fiscalyear", "sector", "subsector", "procurement_type", "procurement_plan",
                            "minor", "minor__selected")
            .prefetch_related("minor__quotes", "minor__payments", "minor__prints", "outputs"))


def summary_counts(rows):
    c = OrderedDict([("all", len(rows)), ("running", 0), ("completed", 0), ("to_approve", 0), ("overdue", 0)])
    for r in rows:
        s = r["summary"]
        c["completed" if s["completed"] else "running"] += 1
        c["to_approve"] += s["current_key"] == "approval"
        c["overdue"] += s["overdue"]
    return c
