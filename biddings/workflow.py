"""बोलपत्र ठेक्का कार्यप्रवाह (workflow) — उपभोक्ता समितिको जस्तै: हरेक ठेक्काका चरण र तिनको स्थिति.

चरण:
    योजना दर्ता → बोलपत्र आह्वान → मूल्याङ्कन → आशयको सूचना → रुजु / स्वीकृत → स्वीकृति र PG माग
    → सम्झौता र कार्यादेश → अन्तिम बिल → अन्तिम भुक्तानी टिप्पणी
ऐच्छिक (सम्झौतापछि): अग्रिम भुक्तानी (+ बैंक जमानत), रनिङ बिल, म्याद थप.

अवस्था (usercommittee.workflow जस्तै): done / current / warning / pending / optional.
"""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from usercommittee.workflow import _link, _modal, add_next, bs_date, sector_note

ZERO = Decimal("0")

STEP_INFO = {
    "project": ("दर्ता", "योजना दर्ता"),
    "notice": ("आह्वान", "लागत अनुमान र बोलपत्र आह्वान"),
    "evaluation": ("मूल्याङ्कन", "बोलपत्र मूल्याङ्कन"),
    "intent": ("आशय", "आशयको सूचना (७ दिन)"),
    "approval": ("स्वीकृत", "रुजु / स्वीकृत"),
    "acceptance": ("PG माग", "स्वीकृति टिप्पणी र PG माग"),
    "agreement": ("सम्झौता", "सम्झौता र कार्यादेश"),
    "final": ("अन्तिम बिल", "अन्तिम मूल्याङ्कन / बिल"),
    "final_tippani": ("टिप्पणी", "अन्तिम भुक्तानी टिप्पणी"),
}
STEPS = list(STEP_INFO)
COLUMNS = [(k, STEP_INFO[k][0], STEP_INFO[k][1]) for k in STEPS]
INTENT_DAYS = 7          # आशयको सूचनापछि उजुरी अवधि
PG_WARN_DAYS = 30        # जमानतको म्याद सकिन लागेको चेतावनी


def D(v):
    return Decimal(str(v or 0))


def _rel(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def np(v):
    """अङ्क नेपालीमा."""
    return str(v).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


def money(v):
    return f"{D(v):,.0f}"


def pct_below(estimate, amount):
    """लागत अनुमानभन्दा कति प्रतिशत घटी (ऋणात्मक = बढी)."""
    est, amt = D(estimate), D(amount)
    if not est or not amt:
        return None
    return round((est - amt) * 100 / est, 2)


def suggested_pg(bid):
    """कार्यसम्पादन जमानत (सार्वजनिक खरिद नियमावली, नियम ११०): कबोल रकमको ५%;
    कबोल रकम लागत अनुमानको ८५% भन्दा कम भए (०.८५ × लागत अनुमान − कबोल) को ५०% थप."""
    amount, est = D(bid.bidding_amount), D(bid.total_cost_estimate)
    if not amount:
        return ZERO
    pg = amount * Decimal("0.05")
    if est and amount < est * Decimal("0.85"):
        pg += (est * Decimal("0.85") - amount) * Decimal("0.5")
    return pg.quantize(Decimal("1"))


def current_bid(project):
    bids = list(project.biddings.all())
    return bids[-1] if bids else None


def can_approve(user):
    from accounts.permissions import has_perm

    return bool(getattr(user, "is_authenticated", False)) and has_perm(user, "bid.approve")


def contract_parts(bid):
    """(contract, bond, requirement, final, advances, runnings) — नभए None/[]."""
    contract = _rel(bid, "contract") if bid else None
    return (
        contract,
        _rel(contract, "bond_issued") if contract else None,
        _rel(bid, "bond_requirement") if bid else None,
        _rel(contract, "final_payment") if contract else None,
        list(contract.advance_payments.all()) if contract else [],
        list(contract.running_evaluations.all()) if contract else [],
    )


def _mb_summary(project):
    from projects.mb import summary

    return summary(project)


def bid_workflow(project, user=None):
    """(steps, summary) — एउटा ठेक्काको चरण-चरण स्थिति र काम (बटन)."""
    from accounts.permissions import user_perms

    P = user_perms(user) if user is not None else set()
    manage, printing = "bid.manage" in P, "bid.print" in P
    bid = current_bid(project)
    approval = _rel(bid, "approval") if bid else None
    contract, bond, req, final, advances, runnings = contract_parts(bid)
    prints = {}
    for pr in (bid.prints.all() if bid else []):
        prints.setdefault(pr.doc_type, pr)
    pid = project.id
    s = {}

    # योजना दर्ता
    s["project"] = {"done": True, "date": None,
                    "note": (project.fiscalyear.name if project.fiscalyear else "") +
                            (f" · विनियोजित रु. {money(project.budget)}" if project.budget else "") + sector_note(project),
                    "actions": [_link("योजना सम्पादन", "edit_project", pid)] if "project.manage" in P else []}

    # लागत अनुमान र बोलपत्र आह्वान
    actions = []
    from projects.procurement import gate_action, plan_gate
    gate = "" if bid else plan_gate(project)
    if gate:
        actions = [gate_action(project)] if P & {"app.manage", "app.approve", "app.view"} else []
    elif manage and not approval:
        actions.append(_link("आह्वान विवरण सम्पादन" if bid else "बोलपत्र आह्वान विवरण भर्नुहोस्", "bid_wf_notice", pid,
                             primary=not bid))
    note = gate
    if bid:
        note = f"ठेक्का नं. {bid.bidding_number}"
        if bid.total_cost_estimate:
            note += f" · लागत अनुमान रु. {money(bid.total_cost_estimate)}"
    s["notice"] = {"done": bool(bid), "date": bid.bid_published_date if bid else None, "note": note,
                   "actions": actions}

    # बोलपत्र मूल्याङ्कन
    evaluated = bool(bid and bid.bidder_name_nepali and bid.bidding_amount)
    actions = []
    if bid and manage and not approval:
        actions.append(_link("मूल्याङ्कन सम्पादन" if evaluated else "मूल्याङ्कन विवरण भर्नुहोस्", "bid_wf_evaluation", pid,
                             primary=not evaluated))
    note = ""
    if evaluated:
        below = pct_below(bid.total_cost_estimate, bid.bidding_amount)
        note = f"{bid.bidder_name_nepali} · कबोल रु. {money(bid.bidding_amount)}"
        if below is not None:
            note += f" ({below}% घटी)" if below >= 0 else f" ({-below}% बढी)"
    s["evaluation"] = {"done": evaluated, "date": bid.bid_evaluation_date if evaluated else None, "note": note,
                       "actions": actions}

    # आशयको सूचना
    asay = prints.get("asay")
    actions = []
    if evaluated and printing:
        actions.append(_link(("✓ " if asay else "") + "आशयको सूचना", "print_asay_notice", bid.id, new_tab=True,
                             primary=not asay))
    note = ""
    days_since = None
    if asay:
        days_since = (date.today() - asay.printed_at.date()).days
        if not approval:
            note = "उजुरी अवधि सकियो" if days_since >= INTENT_DAYS else \
                f"उजुरी अवधि: {np(INTENT_DAYS - days_since)} दिन बाँकी"
    elif evaluated:
        note = "छापेर सार्वजनिक गर्नुहोस् — ७ दिन उजुरी अवधि"
    s["intent"] = {"done": bool(asay), "date": asay.printed_at.date() if asay else None, "note": note,
                   "actions": actions}

    # रुजु / स्वीकृत
    actions = []
    ready = evaluated
    if not approval and ready and user is not None and can_approve(user):
        actions.append(_modal("रुजु / स्वीकृत गर्नुहोस्", "bid_wf_approve", pid, icon="stamp"))
    elif approval and P & {"bid.view"}:
        actions.append(_modal("स्वीकृत विवरण", "bid_wf_approve", pid, primary=False))
    if approval:
        note = f"{approval.approver_name} ({approval.approver_post})" if approval.approver_name else ""
    elif ready:
        note = "प्रमुख प्रशासकीय अधिकृत वा अनुमति पाएका अधिकृतबाट"
    else:
        note = ""
    s["approval"] = {"done": bool(approval), "date": approval.approved_at.date() if approval else None,
                     "note": note, "remarks": approval.remarks if approval else "", "actions": actions}

    # स्वीकृति टिप्पणी र PG माग
    legacy = bool(contract or req)          # कार्यप्रवाह अघिका अभिलेख
    actions = []
    if (approval or legacy) and bid:
        if manage and not bond:
            actions.append(_link("PG माग सम्पादन" if req else "PG माग विवरण भर्नुहोस्", "bid_wf_acceptance", pid,
                                 primary=not req))
        if req and printing:
            actions.append(_link(("✓ " if "tippani" in prints else "") + "स्वीकृति टिप्पणी", "print_contract_tippani",
                                 bid.id, new_tab=True, primary="tippani" not in prints))
            actions.append(_link(("✓ " if "invite" in prints else "") + "सम्झौता गर्न आउने सूचना",
                                 "print_contract_invite", bid.id, new_tab=True, primary="invite" not in prints))
    note = f"PG रु. {money(req.required_amount)} · म्याद {bs_date(req.required_expiry_date)}" if req else \
        (f"सुझाव: PG रु. {money(suggested_pg(bid))}" if approval and bid else "")
    s["acceptance"] = {"done": bool(req and ("invite" in prints or contract)),
                       "date": req.bid_approved_date if req else None, "note": note, "actions": actions}

    # सम्झौता र कार्यादेश
    actions = []
    if req or contract:
        if manage and not bond:
            actions.append(_link("सम्झौता र PG विवरण भर्नुहोस्", "bid_wf_agreement", pid, primary=True))
        if bond and printing:
            actions.append(_link(("✓ " if "contract" in prints else "") + "सम्झौता पत्र", "print_contract_paper",
                                 bond.id, new_tab=True, primary="contract" not in prints))
            actions.append(_link(("✓ " if "work_order" in prints else "") + "कार्यादेश", "print_bid_work_order",
                                 bond.id, new_tab=True, primary="work_order" not in prints))
    note = ""
    if contract and contract.contract_date:
        note = f"सम्पन्न गर्नुपर्ने: {bs_date(contract.current_expiry_date)}"
        if contract.extensions.exists():
            note += " (थपिएको)"
    later = bool(final or advances or runnings)
    s["agreement"] = {"done": bool(bond and (("contract" in prints and "work_order" in prints) or later)),
                      "date": contract.contract_date if contract else None, "note": note, "actions": actions}

    # अन्तिम मूल्याङ्कन / बिल
    actions = []
    if bond and (manage or "uc.valuation" in P):
        if final and "final_tippani" not in prints:
            actions.append(_link("अन्तिम बिल सम्पादन", "bid_wf_final", pid, primary=False))
        elif not final:
            actions.append(_link("अन्तिम बिल भर्नुहोस्", "bid_wf_final", pid, primary=True))
    if final and P & {"bid.manage", "uc.valuation"}:
        n_out = len(project.outputs.all())
        actions.append(_link(("✓ " if n_out else "") + "भौतिक उपलब्धि", "project_outputs", pid, primary=not n_out))
    note = ""
    if final:
        note = f"मूल्याङ्कन रु. {money(final.total_evaluation_amount)} · खुद भुक्तानी रु. {money(final.final_amount)}"
    s["final"] = {"done": bool(final), "date": final.payment_date if final else None, "note": note,
                  "actions": actions}

    # अन्तिम भुक्तानी टिप्पणी
    actions = []
    if final and printing:
        actions.append(_link(("✓ " if "final_tippani" in prints else "") + "अन्तिम टिप्पणी", "print_final_tippani",
                             final.id, new_tab=True, primary="final_tippani" not in prints))
    s["final_tippani"] = {"done": bool(final and "final_tippani" in prints), "date": None,
                          "note": "छापिएपछि अन्तिम बिल लक हुन्छ" if final and "final_tippani" not in prints else "",
                          "actions": actions}

    # ---- पुराना अभिलेख: पछिल्लो चरण भएको भए अघिल्ला भएका मान्ने (छापिएको लग नभए पनि) ----
    later_done = False
    for key in reversed(STEPS):
        info = s[key]
        if info["done"]:
            later_done = True
        elif later_done and key in ("intent", "approval", "acceptance", "agreement"):
            info["done"] = True
            info["note"] = (info["note"] + " · " if info["note"] else "") + "पुरानो अभिलेख"

    # ---- म्याद ----
    today = date.today()
    expiry = contract.current_expiry_date if contract else None
    days_left = (expiry - today).days if expiry else None
    overdue = bool(expiry and days_left < 0 and not final)
    pg_expiry = bond.current_expiry_date if bond else None
    pg_days = (pg_expiry - today).days if pg_expiry else None
    pg_alert = bool(pg_expiry and pg_days <= PG_WARN_DAYS and "final_tippani" not in prints)
    apg_alert = any(_rel(a, "bank_guarantee") and a.bank_guarantee.days_left <= PG_WARN_DAYS for a in advances) \
        and not final

    steps, current = [], None
    for n, key in enumerate(STEPS, start=1):
        info = s[key]
        if info["done"]:
            state = "done"
        elif current is None:
            current = n
            state = "warning" if overdue else "current"
        else:
            state = "pending"
        short, label = STEP_INFO[key]
        steps.append({"n": n, "key": key, "short": short, "label": label, "state": state,
                      "date_bs": bs_date(info.get("date")), **info})
    cur = next((st for st in steps if st["n"] == current), None)

    # ---- ऐच्छिक: अग्रिम, रनिङ, म्याद थप, भेरिएसन ----
    from .contracts import ld_deadline, pct, variation_total
    vtotal = variation_total(contract)
    ldd = ld_deadline(contract)
    ld_days_now = (today - ldd).days if ldd and not final and today > ldd else 0
    adv_total = sum((D(a.approved_amount) for a in advances), ZERO)
    run_net = sum((D(r.net_payable) for r in runnings), ZERO)
    extras = {
        "show": bool(bond),
        "can_add": manage and bond is not None and final is None,
        "advances": advances, "advance_total": adv_total,
        "advance_url": reverse("bid_wf_advance", args=[pid]),
        "runnings": runnings, "running_net": run_net,
        "running_url": reverse("bid_wf_running", args=[pid]),
        "last_cumulative": runnings[-1].total_evaluated_amount if runnings else None,
        "extend_url": reverse("bid_wf_extension", args=[pid]) if bond and manage and not final else "",
        "extensions": contract.extensions.count() if contract else 0,
        "variation_url": reverse("bid_wf_variation", args=[pid]) if bond and manage and not final else "",
        "variations": list(contract.variations.all()) if contract else [],
        "variation_total": vtotal, "variation_pct": pct(vtotal, bid.bidding_amount) if bid else 0,
        "revised_amount": (D(bid.bidding_amount) + vtotal) if bid and bid.bidding_amount else None,
        "ld_deadline_bs": bs_date(ld_deadline(contract)) if contract else "",
        "ld_days": ld_days_now,
        "printing": printing,
        "mb": _mb_summary(project) if bond else None,
        "mb_url": reverse("mb_page", args=[pid]),
    }
    summary = {
        "bid": bid, "contract": contract, "bond": bond, "final": final,
        "current": current, "current_key": cur["key"] if cur else "", "current_label": cur["label"] if cur else "",
        "done_count": sum(1 for st in steps if st["state"] == "done"), "total": len(steps),
        "completed": current is None,
        "overdue": overdue, "days_late": -days_left if overdue else 0,
        "deadline_bs": bs_date(expiry), "days_left": days_left,
        "extended": bool(contract and contract.extensions.exists()),
        "pg_alert": pg_alert, "pg_days": pg_days, "pg_expiry_bs": bs_date(pg_expiry), "apg_alert": apg_alert,
        "intent_days": days_since,
        "extras": extras,
        "contractor": bid.bidder_name_nepali if bid else "",
        "amount": bid.bidding_amount if bid else None,
    }
    return steps, summary


def row_cells(steps):
    by_key = {st["key"]: st for st in steps}
    return [by_key.get(k) for k, _s, _l in COLUMNS]


def with_next(steps, extras, return_to):
    """फारमका link मा ?next= (छाप्ने link मा होइन)."""
    if not return_to:
        return
    for st in steps:
        for a in st.get("actions", []):
            if not a["new_tab"] and not a.get("modal"):
                a["url"] = add_next(a["url"], return_to)
    for k in ("advance_url", "running_url", "extend_url", "variation_url"):
        if extras.get(k):
            extras[k] = add_next(extras[k], return_to)


def workflow_queryset():
    from projects.models import Project

    return (
        Project.objects.filter(procurement_type=2)
        .select_related("ward", "fiscalyear", "sector", "subsector", "procurement_plan", "minor")
        .prefetch_related(
            "outputs", "biddings__prints", "biddings__approval", "biddings__bond_requirement",
            "biddings__contract__bond_issued__extensions", "biddings__contract__extensions",
            "biddings__contract__final_payment", "biddings__contract__advance_payments__bank_guarantee",
            "biddings__contract__variations", "boq_items__measurements",
            "biddings__contract__running_evaluations",
        )
        .order_by("-id")
    )


# ---------------------------------------------------------------- छाप्ने: लग र रोक
def _bid_for(kind, obj_id):
    """print view को id बाट SealedBid."""
    from .models import AdvancePayment, FinalPayment, PerformanceBondIssued, RunningEvaluation, SealedBid

    try:
        if kind == "advance":
            return AdvancePayment.objects.select_related("contract__sealed_bid").get(id=obj_id).contract.sealed_bid
        if kind == "running":
            return RunningEvaluation.objects.select_related("contract__sealed_bid").get(id=obj_id).contract.sealed_bid
        if kind == "bid":
            return SealedBid.objects.get(id=obj_id)
        if kind == "bond":
            return PerformanceBondIssued.objects.select_related("contract__sealed_bid").get(id=obj_id).contract.sealed_bid
        if kind == "final":
            return FinalPayment.objects.select_related("contract__sealed_bid").get(id=obj_id).contract.sealed_bid
    except Exception:
        return None
    return None


def bid_print(view, doc_type, kind, perm="bid.print"):
    """print view: अनुमति र कार्यप्रवाहको क्रम जाँच्ने, छापिएपछि BidPrint राख्ने."""
    from functools import wraps

    from django.contrib import messages
    from django.shortcuts import redirect

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from accounts.permissions import has_perm

        from .models import BidPrint

        if not has_perm(request.user, perm):
            messages.error(request, "यो कागजात छाप्ने अनुमति तपाईंलाई छैन।")
            return redirect("bid_workflow")
        obj_id = kwargs.get("id") or (args[0] if args else None)
        bid = _bid_for(kind, obj_id) if kind else None
        if bid is not None and doc_type:
            problem = gate_problem(bid, doc_type)
            if problem:
                messages.error(request, f"“{bid.project.name}”: {problem}")
                return redirect(back_url(bid))
        response = view(request, *args, **kwargs)
        if getattr(response, "status_code", None) == 200:
            if bid is not None and doc_type:
                BidPrint.objects.create(sealed_bid=bid, doc_type=doc_type,
                                        printed_by=request.user if request.user.is_authenticated else None)
            # छापिसकेपछि सधैँ कार्यप्रवाहमा (त्यही ठेक्काको panel खुला)
            if hasattr(response, "content") and b"__BID_RETURN__" in response.content:
                response.content = response.content.replace(b"__BID_RETURN__", back_url(bid).encode())
        return response

    return wrapper


def back_url(bid):
    url = reverse("bid_workflow")
    return f"{url}?open={bid.project_id}" if bid is not None else url


def gate_problem(bid, doc_type):
    """क्रम नमिलेमा कारण (नत्र None). पुराना अभिलेख (सम्झौता भइसकेका) लाई नरोक्ने."""
    contract = _rel(bid, "contract")
    legacy = contract is not None
    if doc_type == "asay" and not (bid.bidder_name_nepali and bid.bidding_amount):
        return "आशयको सूचना अघि बोलपत्र मूल्याङ्कन (छनोट भएको बोलपत्रदाता र कबोल रकम) चाहिन्छ।"
    if doc_type in ("tippani", "invite") and not legacy and not _rel(bid, "approval"):
        return "स्वीकृति टिप्पणी / सम्झौता सूचना अघि रुजु / स्वीकृत हुनुपर्छ।"
    if doc_type in ("tippani", "invite") and not _rel(bid, "bond_requirement"):
        return "पहिले PG माग विवरण भर्नुहोस्।"
    return None
