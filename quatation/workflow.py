"""दरभाउपत्र खरिद कार्यप्रवाह (workflow) — उपभोक्ता समिति र बोलपत्र ठेक्का जस्तै.

चरण:
    योजना दर्ता → लागत अनुमान र आह्वान → आह्वान पत्र → दरभाउपत्र प्राप्ति र तुलना → रुजु / स्वीकृत
    → सम्झौता र कार्यादेश → अन्तिम बिल → अन्तिम भुक्तानी टिप्पणी
"""
import json
from datetime import date
from decimal import Decimal

from django.urls import reverse

from usercommittee.workflow import _link, _modal, add_next, bs_date, sector_note

ZERO = Decimal("0")
MIN_FIRMS = 3            # सार्वजनिक खरिद नियमावली: कम्तीमा ३ सूचीकृत फर्मबाट दरभाउपत्र

STEP_INFO = {
    "project": ("दर्ता", "योजना दर्ता"),
    "invite": ("आह्वान", "लागत अनुमान र दरभाउपत्र आह्वान"),
    "invite_letter": ("पत्र", "आह्वान टिप्पणी र पत्र"),
    "quotes": ("तुलना", "दरभाउपत्र प्राप्ति र तुलना"),
    "approval": ("स्वीकृत", "रुजु / स्वीकृत"),
    "agreement": ("सम्झौता", "सम्झौता र कार्यादेश"),
    "final": ("अन्तिम बिल", "अन्तिम मूल्याङ्कन / बिल"),
    "final_tippani": ("टिप्पणी", "अन्तिम भुक्तानी टिप्पणी"),
}
STEPS = list(STEP_INFO)
GUARANTEE_WARN_DAYS = 30   # अग्रिम भुक्तानी जमानतको म्याद सकिन लागेको चेतावनी
COLUMNS = [(k, STEP_INFO[k][0], STEP_INFO[k][1]) for k in STEPS]


def D(v):
    return Decimal(str(v or 0))


def money(v):
    return f"{D(v):,.0f}"


def np(v):
    return str(v).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


def _rel(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def bids(q):
    """[(firm_name, Decimal price)] — bidded_prices: पुरानो ढाँचा '{"योजना": [{"फर्म": मूल्य}, ...]}' (text वा dict)."""
    raw = q.bidded_prices if q is not None else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    out = []
    if isinstance(raw, dict):
        for items in raw.values():
            for item in items or []:
                for firm, price in (item or {}).items():
                    try:
                        out.append((firm, Decimal(str(price))))
                    except Exception:
                        pass
    return out


def dump_bids(q, pairs):
    """[(firm_name, price)] → पुरानो ढाँचामा (पुराना छाप्ने पेजले पढ्ने)."""
    q.bidded_prices = json.dumps({q.project.name: [{f: float(p)} for f, p in pairs]}, ensure_ascii=False)


def lowest(q):
    pairs = bids(q)
    return min(pairs, key=lambda x: x[1]) if pairs else (None, None)


def pct_below(estimate, amount):
    est, amt = D(estimate), D(amount)
    if not est or not amt:
        return None
    return round((est - amt) * 100 / est, 2)


def current_quation(project):
    qs = list(project.quation_set.all())
    return qs[-1] if qs else None


def final_of(q):
    finals = list(q.quationfinal_set.all()) if q is not None else []
    return finals[-1] if finals else None


def can_approve(user):
    from accounts.permissions import has_perm

    return bool(getattr(user, "is_authenticated", False)) and has_perm(user, "quot.approve")


def quot_workflow(project, user=None):
    from accounts.permissions import user_perms

    P = user_perms(user) if user is not None else set()
    manage, printing = "quot.manage" in P, "quot.print" in P
    q = current_quation(project)
    approval = _rel(q, "approval") if q else None
    fin = final_of(q)
    prints = {}
    for pr in (q.prints.all() if q else []):
        prints.setdefault(pr.doc_type, pr)
    firms = list(q.suchikrit.all()) if q else []
    pairs = bids(q)
    low_firm, low_price = lowest(q)
    advances = list(q.advances.all()) if q else []
    pid = project.id
    s = {}

    s["project"] = {"done": True, "date": None,
                    "note": (project.fiscalyear.name if project.fiscalyear else "") +
                            (f" · विनियोजित रु. {money(project.budget)}" if project.budget else "") + sector_note(project),
                    "actions": [_link("योजना सम्पादन", "edit_project", pid)] if "project.manage" in P else []}

    # लागत अनुमान र आह्वान
    actions = []
    from projects.procurement import gate_action, plan_gate
    gate = "" if q else plan_gate(project)
    if gate:
        actions = [gate_action(project)] if P & {"app.manage", "app.approve", "app.view"} else []
    elif manage and not pairs:
        actions.append(_link("आह्वान सम्पादन" if q else "लागत अनुमान र फर्म छान्नुहोस्", "quot_wf_invite", pid,
                             primary=not q))
    note = gate
    if q:
        note = f"लागत अनुमान रु. {money(q.cost_estimate)} · {np(len(firms))} फर्म"
        if q.submission_deadline:
            note += f" · पेश गर्ने अन्तिम मिति {bs_date(q.submission_deadline)}"
    s["invite"] = {"done": bool(q), "date": q.invite_date if q else None, "note": note, "actions": actions}

    # आह्वान टिप्पणी र पत्र
    actions = []
    if q and printing:
        actions.append(_link(("✓ " if "invite_tippani" in prints else "") + "आह्वान टिप्पणी", "print_quatation_tippani",
                             q.id, new_tab=True, primary="invite_tippani" not in prints))
        actions.append(_link(("✓ " if "invite_letter" in prints else "") + "फर्मलाई आह्वान पत्र", "send_quatation_letter",
                             q.id, new_tab=True, primary="invite_letter" not in prints))
    letter = prints.get("invite_letter")
    s["invite_letter"] = {"done": bool(letter), "date": letter.printed_at.date() if letter else None,
                          "note": f"{np(len(firms))} फर्मलाई पत्र" if q else "", "actions": actions}

    # प्राप्ति र तुलना
    actions = []
    if q and manage and not approval:
        actions.append(_link("प्राप्त दर सम्पादन" if pairs else "प्राप्त दरभाउपत्र भर्नुहोस्", "quot_wf_quotes", pid,
                             primary=not pairs))
    note = ""
    if pairs:
        below = pct_below(q.cost_estimate, low_price)
        note = f"{np(len(pairs))} वटा प्राप्त · न्यूनतम {low_firm} रु. {money(low_price)}"
        if below is not None:
            note += f" ({below}% घटी)" if below >= 0 else f" ({-below}% बढी)"
    s["quotes"] = {"done": bool(pairs), "date": q.opening_date if q and pairs else None, "note": note,
                   "actions": actions}

    # रुजु / स्वीकृत
    actions = []
    if not approval and pairs and user is not None and can_approve(user):
        actions.append(_modal("रुजु / स्वीकृत गर्नुहोस्", "quot_wf_approve", pid, icon="stamp"))
    elif approval and "quot.view" in P:
        actions.append(_modal("स्वीकृत विवरण", "quot_wf_approve", pid, primary=False))
    note = ""
    if approval:
        note = f"{approval.approver_name} ({approval.approver_post})"
    elif pairs:
        note = "प्रमुख प्रशासकीय अधिकृत वा अनुमति पाएका अधिकृतबाट"
    s["approval"] = {"done": bool(approval), "date": approval.approved_at.date() if approval else None,
                     "note": note, "remarks": approval.remarks if approval else "", "actions": actions}

    # सम्झौता र कार्यादेश
    legacy = bool(q and q.agreement_date and not approval)
    actions = []
    if approval or legacy:
        if printing:
            actions.append(_link(("✓ " if "approval_tippani" in prints else "") + "स्वीकृति टिप्पणी",
                                 "approved_quatation_tippani", q.id, new_tab=True,
                                 primary="approval_tippani" not in prints))
        if manage and not fin:
            actions.append(_link("सम्झौता मिति सम्पादन" if q.agreement_date else "सम्झौता विवरण भर्नुहोस्",
                                 "quot_wf_agreement", pid, primary=not q.agreement_date))
        if q.agreement_date and printing:
            actions.append(_link(("✓ " if "agreement" in prints else "") + "सम्झौता पत्र", "print_quatation_agreement",
                                 q.id, new_tab=True, primary="agreement" not in prints))
            actions.append(_link(("✓ " if "work_order" in prints else "") + "कार्यादेश", "print_quatation_work_order",
                                 q.id, new_tab=True, primary="work_order" not in prints))
    note = f"सम्पन्न गर्नुपर्ने: {bs_date(q.expire_date)}" if q and q.expire_date else ""
    s["agreement"] = {"done": bool(q and q.agreement_date and (("agreement" in prints and "work_order" in prints) or fin)),
                      "date": q.agreement_date if q else None, "note": note, "actions": actions}

    # अन्तिम बिल
    actions = []
    if q and q.agreement_date and (manage or "uc.valuation" in P) and "final_tippani" not in prints:
        actions.append(_link("अन्तिम बिल सम्पादन" if fin else "अन्तिम बिल भर्नुहोस्", "quot_wf_final", pid,
                             primary=not fin))
    if fin and P & {"quot.manage", "uc.valuation"}:
        n_out = len(project.outputs.all())
        actions.append(_link(("✓ " if n_out else "") + "भौतिक उपलब्धि", "project_outputs", pid, primary=not n_out))
    note = f"मूल्याङ्कन रु. {money(fin.totalValuation)} · खुद भुक्तानी रु. {money(fin.finalpayment)}" if fin else ""
    if advances and not fin:
        note = f"अग्रिम रु. {money(sum(D(a.approved_amount) for a in advances))} कट्टी हुने"
    s["final"] = {"done": bool(fin), "date": fin.application_date if fin else None, "note": note, "actions": actions}

    # अन्तिम टिप्पणी
    actions = []
    if fin and printing:
        actions.append(_link(("✓ " if "final_tippani" in prints else "") + "अन्तिम टिप्पणी",
                             "print_quatation_final_payment_tippani", fin.id, new_tab=True,
                             primary="final_tippani" not in prints))
    s["final_tippani"] = {"done": bool(fin and "final_tippani" in prints), "date": None,
                          "note": "छापिएपछि अन्तिम बिल लक हुन्छ" if fin and "final_tippani" not in prints else "",
                          "actions": actions}

    # पुराना अभिलेख: पछिल्लो चरण भएको भए अघिल्ला भएका मान्ने
    later_done = False
    for key in reversed(STEPS):
        if s[key]["done"]:
            later_done = True
        elif later_done and key in ("invite_letter", "approval", "agreement"):
            s[key]["done"] = True
            s[key]["note"] = (s[key]["note"] + " · " if s[key]["note"] else "") + "पुरानो अभिलेख"

    today = date.today()
    expiry = q.expire_date if q else None
    days_left = (expiry - today).days if expiry else None
    overdue = bool(expiry and days_left < 0 and not fin)
    deadline_passed = bool(q and q.submission_deadline and q.submission_deadline < today and not pairs)
    apg_alert = bool(not fin and any(a.days_left <= GUARANTEE_WARN_DAYS for a in advances))

    steps, current = [], None
    for n, key in enumerate(STEPS, start=1):
        info = s[key]
        if info["done"]:
            state = "done"
        elif current is None:
            current = n
            state = "warning" if overdue or (key == "quotes" and deadline_passed) else "current"
        else:
            state = "pending"
        short, label = STEP_INFO[key]
        steps.append({"n": n, "key": key, "short": short, "label": label, "state": state,
                      "date_bs": bs_date(info.get("date")), **info})
    cur = next((st for st in steps if st["n"] == current), None)
    return steps, {
        "q": q, "final": fin, "firms": firms, "bids": pairs,
        "current": current, "current_key": cur["key"] if cur else "", "current_label": cur["label"] if cur else "",
        "done_count": sum(1 for st in steps if st["state"] == "done"), "total": len(steps),
        "completed": current is None, "overdue": overdue, "days_late": -days_left if overdue else 0,
        "deadline_bs": bs_date(expiry), "submission_bs": bs_date(q.submission_deadline) if q else "",
        "deadline_passed": deadline_passed, "apg_alert": apg_alert,
        "advance": {
            "show": bool(q and q.agreement_date),
            "list": advances, "total": sum((D(a.approved_amount) for a in advances), ZERO),
            "can_add": manage and bool(q and q.agreement_date) and fin is None,
            "url": reverse("quot_wf_advance", args=[pid]), "printing": printing,
        },
        "contractor": (approval.firm_name if approval and approval.firm_name else low_firm) or "",
        "amount": (approval.amount if approval and approval.amount else low_price),
    }


def row_cells(steps):
    by_key = {st["key"]: st for st in steps}
    return [by_key.get(k) for k, _s, _l in COLUMNS]


def with_next(steps, return_to, summary=None):
    if not return_to:
        return
    if summary and summary.get("advance"):
        summary["advance"]["url"] = add_next(summary["advance"]["url"], return_to)
    for st in steps:
        for a in st.get("actions", []):
            if not a["new_tab"] and not a.get("modal"):
                a["url"] = add_next(a["url"], return_to)


def workflow_queryset():
    from projects.models import Project

    return (
        Project.objects.filter(procurement_type=3)
        .select_related("ward", "fiscalyear", "sector", "subsector", "procurement_plan", "minor")
        .prefetch_related("outputs", "quation_set__suchikrit", "quation_set__prints", "quation_set__approval",
                          "quation_set__quationfinal_set", "quation_set__advances")
        .order_by("-id")
    )


# ---------------------------------------------------------------- छाप्ने: अनुमति, क्रम, लग, फर्कने ठाउँ
def _quation_for(kind, obj_id):
    from .models import Quation, QuationFinal

    try:
        if kind == "q":
            return Quation.objects.select_related("project").get(id=int(obj_id))
        if kind == "advance":
            from .models import QuationAdvance

            return QuationAdvance.objects.select_related("quation__project").get(id=int(obj_id)).quation
        if kind == "final":
            return QuationFinal.objects.select_related("quation__project").get(id=int(obj_id)).quation
    except Exception:
        return None
    return None


def back_url(q):
    url = reverse("quot_workflow")
    return f"{url}?open={q.project_id}" if q is not None else url


def gate_problem(q, doc_type):
    pairs = bids(q)
    if doc_type == "approval_tippani" and not pairs:
        return "स्वीकृति टिप्पणी अघि प्राप्त दरभाउपत्र भर्नुहोस्।"
    if doc_type == "approval_tippani" and not _rel(q, "approval") and not q.agreement_date:
        return "स्वीकृति टिप्पणी अघि रुजु / स्वीकृत हुनुपर्छ।"
    if doc_type in ("agreement", "work_order") and not q.agreement_date:
        return "पहिले सम्झौता मिति भर्नुहोस्।"
    return None


def quot_print(view, doc_type, kind):
    from functools import wraps

    from django.contrib import messages
    from django.shortcuts import redirect

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from accounts.permissions import has_perm

        from .models import QuationPrint

        if not has_perm(request.user, "quot.print"):
            messages.error(request, "यो कागजात छाप्ने अनुमति तपाईंलाई छैन।")
            return redirect("quot_workflow")
        q = _quation_for(kind, kwargs.get("id") or (args[0] if args else None))
        if q is not None:
            problem = gate_problem(q, doc_type)
            if problem:
                messages.error(request, f"“{q.project.name}”: {problem}")
                return redirect(back_url(q))
        response = view(request, *args, **kwargs)
        if getattr(response, "status_code", None) == 200:
            if q is not None and doc_type:
                QuationPrint.objects.create(quation=q, doc_type=doc_type,
                                            printed_by=request.user if request.user.is_authenticated else None)
            if hasattr(response, "content") and b"__WF_RETURN__" in response.content:
                response.content = response.content.replace(b"__WF_RETURN__", back_url(q).encode())
        return response

    return wrapper
