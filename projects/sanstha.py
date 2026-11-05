"""संस्था / समिति मार्फतको खरिद — दरभाउपत्र जस्तै पूरा कार्यप्रवाह (ऐन दफा ४६).

चरण:
    खरिद योजना → लागत अनुमान र प्रस्ताव आह्वान → आह्वान टिप्पणी र पत्र / सूचना → प्रस्ताव प्राप्ति र मूल्याङ्कन
    → रुजु / स्वीकृत → सम्झौता र कार्यादेश → (किस्ता भुक्तानी — ऐच्छिक) → काम सम्पन्न प्रतिवेदन
    → अन्तिम बिल → अन्तिम भुक्तानी टिप्पणी

नियम (सर्भरमा जाँचिन्छ):
  * खरिद योजना स्वीकृत नभई आह्वान गर्न नमिल्ने (सेटिङ खुला भए)
  * आह्वान: सूचीकृत संस्थालाई पत्र भए कम्तीमा ३ संस्था; सार्वजनिक सूचना भए कम्तीमा १५ दिन;
    लागत अनुमान पालिकाको सीमा (सेटिङ) भन्दा बढी भए सार्वजनिक सूचना / आशयपत्र अनिवार्य
  * कालोसूचीमा (पालिका वा PPMO) परेका संस्था आह्वान / प्रस्तावमा नमिल्ने
  * प्रस्ताव पेश गर्ने अन्तिम मितिअघि खोल्न नमिल्ने
  * छनौट: योग्य र (न्यूनतम अङ्क तोकिए) प्राविधिक अङ्क पुगेकामध्ये न्यूनतम रकम; अर्को छान्दा कारण अनिवार्य;
    लागत अनुमानभन्दा बढी स्वीकृत नहुने
  * सम्झौता रकम स्वीकृत प्रस्तावभन्दा बढी नहुने; कुल भुक्तानी जाँचपास रकम र विनियोजित बजेटभित्र
  * अन्तिम भुक्तानी टिप्पणी छापिएपछि अन्तिम बिल लक
डाटा: MinorProcurement (method="sanstha") — प्रतिवेदन, कट्टी, फर्मको इतिहास पहिलेकै जस्तै चल्छन्।
"""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from usercommittee.workflow import _link, _modal, add_next, bs_date, sector_note

from . import minor as mn

ZERO = Decimal("0")
MIN_ORGS = 3            # पत्रबाट आह्वान गर्दा कम्तीमा ३ सूचीकृत संस्था (दरभाउपत्र जस्तै)
NOTICE_DAYS = mn.SANSTHA_NOTICE_DAYS   # सार्वजनिक सूचना कम्तीमा १५ दिन
LABEL = "संस्था / समिति मार्फत खरिद"

STEP_INFO = {
    "plan": ("योजना", "खरिद योजना स्वीकृत"),
    "invite": ("आह्वान", "लागत अनुमान र प्रस्ताव आह्वान"),
    "invite_letter": ("पत्र", "आह्वान टिप्पणी र पत्र / सूचना"),
    "proposals": ("प्रस्ताव", "प्रस्ताव प्राप्ति र मूल्याङ्कन"),
    "approval": ("स्वीकृत", "रुजु / स्वीकृत"),
    "agreement": ("सम्झौता", "सम्झौता र कार्यादेश"),
    "completion": ("प्रतिवेदन", "काम सम्पन्न प्रतिवेदन"),
    "final": ("अन्तिम बिल", "अन्तिम बिल / भुक्तानी"),
    "final_tippani": ("टिप्पणी", "अन्तिम भुक्तानी टिप्पणी"),
}
STEPS = list(STEP_INFO)
COLUMNS = [(k, STEP_INFO[k][0], STEP_INFO[k][1]) for k in STEPS]


def D(v):
    return Decimal(str(v or 0))


def money(v):
    return f"{D(v):,.0f}"


def np(v):
    return str(v).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


def pct_below(estimate, amount):
    est, amt = D(estimate), D(amount)
    if not est or not amt:
        return None
    return round((est - amt) * 100 / est, 2)


def is_sanstha(project):
    return mn.method_of(project) == "sanstha"


def eligible(m, quote):
    """छनौट योग्य: योग्य चिन्ह लागेको र न्यूनतम अङ्क तोकिएको भए अङ्क पुगेको."""
    if not quote.qualified:
        return False
    if m.pass_mark is not None:
        return quote.tech_score is not None and D(quote.tech_score) >= D(m.pass_mark)
    return True


def ranked(m):
    """[(quote, eligible)] — योग्य पहिले, रकम बढ्दो क्रममा."""
    if m is None:
        return []
    qs = sorted(m.quotes.all(), key=lambda q: (not eligible(m, q), D(q.amount), q.id))
    return [(q, eligible(m, q)) for q in qs]


def recommended(m):
    r = ranked(m)
    return r[0][0] if r and r[0][1] else None


def prints_of(m):
    out = {}
    for p in (m.prints.all() if m else []):
        out.setdefault(p.doc_type, p)
    return out


def installments(m):
    return [p for p in (m.payments.all() if m else []) if p.kind != "final"]


def workflow(project, user=None):
    from accounts.permissions import user_perms

    from .procurement import gate_action, plan_gate

    P = user_perms(user) if user is not None else set()
    manage, printing, approver = "minor.manage" in P, "minor.print" in P, "minor.approve" in P
    m = mn.minor_of(project)
    if m is not None and m.method != "sanstha":
        m = None
    prints = prints_of(m)
    quotes = list(m.quotes.all()) if m else []
    rank = ranked(m)
    rec = recommended(m)
    fin = mn.final_payment(m)
    inst = installments(m)
    invited = list(m.invited.all()) if m else []
    pid = project.id
    s = {}

    gate = "" if m else plan_gate(project)
    s["plan"] = {"done": not gate, "date": None,
                 "note": gate or ((project.fiscalyear.name if project.fiscalyear else "") +
                                  (f" · विनियोजित रु. {money(project.budget)}" if project.budget else "") + sector_note(project)),
                 "actions": ([gate_action(project)] if gate and P & {"app.manage", "app.approve", "app.view"} else
                             [_link("योजना सम्पादन", "edit_project", pid)] if "project.manage" in P else [])}

    # लागत अनुमान र आह्वान
    actions = []
    if not gate and manage and not quotes:
        actions.append(_link("आह्वान सम्पादन" if m else "लागत अनुमान र आह्वान", "sanstha_invite", pid, primary=not m))
    note = ""
    if m:
        note = f"लागत अनुमान रु. {money(m.estimate_amount)}"
        if m.notice_kind:
            note += f" · {m.get_notice_kind_display()}"
        if invited:
            note += f" · {np(len(invited))} संस्था"
        if m.submission_deadline:
            note += f" · पेश गर्ने अन्तिम मिति {bs_date(m.submission_deadline)}"
    s["invite"] = {"done": bool(m and m.notice_date), "date": m.notice_date if m else None, "note": note, "actions": actions}

    # आह्वान टिप्पणी र पत्र / सूचना
    actions = []
    if m and m.notice_date and printing:
        actions.append(_link(("✓ " if "invite_tippani" in prints else "") + "आह्वान टिप्पणी", "sanstha_print", pid,
                             "invite_tippani", new_tab=True, primary="invite_tippani" not in prints))
        actions.append(_link(("✓ " if "invite_letter" in prints else "") +
                             ("सार्वजनिक सूचना" if m.notice_kind == "public" else "आह्वान पत्र / सूचना"),
                             "sanstha_print", pid, "invite_letter", new_tab=True, primary="invite_letter" not in prints))
    letter = prints.get("invite_letter")
    s["invite_letter"] = {"done": bool(letter), "date": letter.printed_at.date() if letter else None,
                          "note": (f"{np(len(invited))} संस्थालाई पत्र" if invited else "") if m else "", "actions": actions}

    # प्रस्ताव प्राप्ति र मूल्याङ्कन
    actions = []
    if m and m.notice_date and manage and not m.approved_at:
        actions.append(_link("प्रस्ताव सम्पादन" if quotes else "प्राप्त प्रस्ताव भर्नुहोस्", "sanstha_proposals", pid,
                             primary=not quotes))
    note = ""
    if quotes:
        note = f"{np(len(quotes))} प्रस्ताव · योग्य {np(sum(1 for _q, e in rank if e))}"
        if rec:
            below = pct_below(m.estimate_amount, rec.amount)
            note += f" · सिफारिस {rec.name} रु. {money(rec.amount)}"
            if below is not None:
                note += f" ({below}% घटी)" if below >= 0 else f" ({-below}% बढी)"
    s["proposals"] = {"done": bool(quotes and (m.opening_date or m.approved_at)), "date": m.opening_date if m else None,
                      "note": note, "actions": actions}

    # रुजु / स्वीकृत
    actions = []
    if m and not m.approved_at and quotes and approver:
        actions.append(_modal("रुजु / स्वीकृत गर्नुहोस्", "sanstha_approve", pid, icon="stamp"))
    elif m and m.approved_at and P & {"minor.view", "minor.manage", "minor.approve", "minor.print"}:
        actions.append(_modal("स्वीकृत विवरण", "sanstha_approve", pid, primary=False))
    note = ""
    if m and m.approved_at:
        note = (f"{m.selected.name} · " if m.selected else "") + m.approver_name
    elif quotes:
        note = "प्रमुख प्रशासकीय अधिकृत वा अनुमति पाएका अधिकृतबाट"
    s["approval"] = {"done": bool(m and m.approved_at), "date": m.approved_at.date() if m and m.approved_at else None,
                     "note": note, "remarks": m.approval_remarks if m and m.approved_at else "", "actions": actions}

    # सम्झौता र कार्यादेश
    actions = []
    if m and m.approved_at:
        if printing:
            actions.append(_link(("✓ " if "approval" in prints else "") + "स्वीकृति टिप्पणी", "sanstha_print", pid,
                                 "approval", new_tab=True, primary="approval" not in prints))
        if manage and not inst and not fin:
            actions.append(_link("सम्झौता सम्पादन" if m.order_date else "सम्झौता विवरण भर्नुहोस्", "sanstha_agreement", pid,
                                 primary=not m.order_date))
        if m.order_date and printing:
            actions.append(_link(("✓ " if "order" in prints else "") + "सम्झौता पत्र", "sanstha_print", pid, "order",
                                 new_tab=True, primary="order" not in prints))
            actions.append(_link(("✓ " if "work_order" in prints else "") + "कार्यादेश", "sanstha_print", pid, "work_order",
                                 new_tab=True, primary="work_order" not in prints))
    note = ""
    if m and m.order_date:
        note = f"रु. {money(m.order_amount)}" + (f" · नं. {m.order_no}" if m.order_no else "") + \
               (f" · सम्पन्न गर्नुपर्ने {bs_date(m.due_date)}" if m.due_date else "")
        if m.cost_share:
            note += f" · संस्थाको सहभागिता रु. {money(m.cost_share)}"
    s["agreement"] = {"done": bool(m and m.order_date and (("order" in prints and "work_order" in prints)
                                                          or m.completed_on or fin)),
                      "date": m.order_date if m else None, "note": note, "actions": actions}

    # काम सम्पन्न प्रतिवेदन
    actions = []
    if m and m.order_date and manage and not fin:
        actions.append(_link("प्रतिवेदन सम्पादन" if m.completed_on else "काम सम्पन्न प्रतिवेदन", "sanstha_completion", pid,
                             primary=not m.completed_on))
    if m and m.completed_on and P & {"minor.manage", "uc.valuation"}:
        n_out = len(project.outputs.all())
        actions.append(_link(("✓ " if n_out else "") + "भौतिक उपलब्धि", "project_outputs", pid, primary=not n_out))
    s["completion"] = {"done": bool(m and m.completed_on), "date": m.completed_on if m else None,
                       "note": f"जाँचपास रु. {money(m.completion_value)}" if m and m.completed_on else "", "actions": actions}

    # अन्तिम बिल
    actions = []
    if m and m.completed_on and manage and "payment" not in prints:
        actions.append(_link("अन्तिम बिल सम्पादन" if fin else "अन्तिम बिल भर्नुहोस्", "sanstha_final", pid, primary=not fin))
    note = f"कुल रु. {money(fin.gross)} · खुद रु. {money(fin.net)}" if fin else ""
    if inst and not fin:
        note = f"{np(len(inst))} किस्ता रु. {money(sum(D(p.gross) for p in inst))} भुक्तानी भइसकेको"
    s["final"] = {"done": bool(fin), "date": fin.date if fin else None, "note": note, "actions": actions}

    # अन्तिम टिप्पणी
    actions = []
    if fin and printing:
        actions.append(_link(("✓ " if "payment" in prints else "") + "अन्तिम भुक्तानी टिप्पणी", "sanstha_print", pid,
                             "payment", new_tab=True, primary="payment" not in prints))
    s["final_tippani"] = {"done": bool(fin and "payment" in prints), "date": None,
                          "note": "छापिएपछि अन्तिम बिल लक हुन्छ" if fin and "payment" not in prints else "",
                          "actions": actions}

    # पुराना अभिलेख (पुरानो पेजबाट भरिएका): पछिल्लो चरण भएको भए पत्र / सम्झौता भएको मान्ने
    later = False
    for key in reversed(STEPS):
        if s[key]["done"]:
            later = True
        elif later and key in ("invite_letter", "proposals", "agreement"):
            s[key]["done"] = True
            tag = "छापिएको अभिलेख छैन" if (m and m.submission_deadline) else "पुरानो अभिलेख"
            s[key]["note"] = (s[key]["note"] + " · " if s[key]["note"] else "") + tag

    today = date.today()
    due = m.due_date if m else None
    days_left = (due - today).days if due else None
    overdue = bool(due and days_left < 0 and not (m and m.completed_on))
    deadline_passed = bool(m and m.submission_deadline and m.submission_deadline < today and not quotes)

    steps, current = [], None
    for n, key in enumerate(STEPS, start=1):
        info = s[key]
        if info["done"]:
            state = "done"
        elif current is None:
            current = n
            state = "warning" if overdue or (key == "proposals" and deadline_passed) else "current"
        else:
            state = "pending"
        short, label = STEP_INFO[key]
        steps.append({"n": n, "key": key, "short": short, "label": label, "state": state,
                      "date_bs": bs_date(info.get("date")), **info})
    cur = next((st for st in steps if st["n"] == current), None)
    selected = m.selected if m and m.selected else None
    return steps, {
        "m": m, "final": fin, "invited": invited, "quotes": quotes, "ranked": rank, "recommended": rec,
        "current": current, "current_key": cur["key"] if cur else "", "current_label": cur["label"] if cur else "",
        "done_count": sum(1 for st in steps if st["state"] == "done"), "total": len(steps),
        "completed": current is None, "overdue": overdue, "days_late": -days_left if overdue else 0,
        "deadline_bs": bs_date(due), "submission_bs": bs_date(m.submission_deadline) if m else "",
        "deadline_passed": deadline_passed,
        "org": (selected.name if selected else (rec.name if rec else "")),
        "amount": (m.order_amount or selected.amount) if selected else (rec.amount if rec else None),
        "installments": {
            "show": bool(m and m.order_date), "list": inst, "total": sum((D(p.gross) for p in inst), ZERO),
            "can_add": manage and bool(m and m.order_date) and not (m.completed_on if m else False) and fin is None,
            "url": reverse("sanstha_installment", args=[pid]), "printing": printing,
        },
    }


def row_cells(steps):
    by_key = {st["key"]: st for st in steps}
    return [by_key.get(k) for k, _s, _l in COLUMNS]


def with_next(steps, return_to, summary=None):
    if not return_to:
        return
    if summary and summary.get("installments"):
        summary["installments"]["url"] = add_next(summary["installments"]["url"], return_to)
    for st in steps:
        for a in st.get("actions", []):
            if not a["new_tab"] and not a.get("modal"):
                a["url"] = add_next(a["url"], return_to)


def workflow_queryset():
    from .models import Project

    return (Project.objects.filter(procurement_type__code="sanstha")
            .select_related("ward", "fiscalyear", "sector", "subsector", "procurement_type", "procurement_plan",
                            "minor", "minor__selected")
            .prefetch_related("minor__quotes", "minor__payments", "minor__prints", "minor__invited", "outputs")
            .order_by("-id"))


def print_problem(m, doc, payment=None):
    """छाप्ने चरण पुगेको छैन भने कारण."""
    if m is None:
        return "पहिले लागत अनुमान र आह्वान दर्ता गर्नुहोस्।"
    need = {
        "invite_tippani": (m.notice_date, "पहिले आह्वान विवरण भर्नुहोस्।"),
        "invite_letter": (m.notice_date, "पहिले आह्वान विवरण भर्नुहोस्।"),
        "approval": (m.approved_at, "स्वीकृति टिप्पणी अघि रुजु / स्वीकृत हुनुपर्छ।"),
        "order": (m.order_date, "पहिले सम्झौता विवरण भर्नुहोस्।"),
        "work_order": (m.order_date, "पहिले सम्झौता विवरण भर्नुहोस्।"),
        "installment": (payment is not None, "किस्ता भेटिएन।"),
        "payment": (mn.final_payment(m) is not None, "पहिले अन्तिम बिल भर्नुहोस्।"),
    }
    if doc not in need:
        return "अमान्य कागजात।"
    ok, msg = need[doc]
    return "" if ok else msg
