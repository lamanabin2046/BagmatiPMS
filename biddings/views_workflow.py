"""बोलपत्र ठेक्का कार्यप्रवाह — सूची, चरण panel, हरेक चरणको फारम र रुजु / स्वीकृत.

फारम पुराना (मेनुका) फारमभन्दा फरक: योजना पहिल्यै छानिएको, सम्पादन गर्न मिल्ने, सर्भरमा रकम/मिति जाँच,
सुरक्षित गरेपछि कार्यप्रवाहमै फर्किने (ReturnToNextMiddleware, ?next=).
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import Ward
from accounts.permissions import has_perm, user_perms
from projects.budget import check_payment, over_budget_warning
from projects.budget import spent as budget_spent
from projects.models import FiscalYear
from usercommittee.workflow import approver_identity, bs_date

from .models import (AdvanceBankGuarantee, AdvancePayment, BidApproval, Contract, FinalPayment,
                     PerformanceBondIssued, PerformanceBondRequirement, RunningEvaluation, SealedBid)
from .workflow import (COLUMNS, INTENT_DAYS, ZERO, D, bid_workflow, can_approve, contract_parts, current_bid,
                       money, np, pct_below, row_cells, suggested_pg, with_next, workflow_queryset)

NP_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


# ---------------------------------------------------------------- सहायक
def to_ad(value):
    """'२०८२-०४-१५' / '2082-04-15' (वि.सं.) → date, नमिले None."""
    from nepali.date_converter import converter

    value = (value or "").strip().translate(NP_DIGITS)
    if not value:
        return None
    try:
        y, m, d = map(int, value.split("-"))
        return date(*converter.nepali_to_english(y, m, d))
    except Exception:
        return None


def to_bs(d):
    """date → '2082-04-15' (फारममा भर्ने, अङ्ग्रेजी अङ्क)."""
    from nepali.date_converter import converter

    if not d:
        return ""
    try:
        y, m, dd = converter.english_to_nepali(d.year, d.month, d.day)
        return f"{y}-{m:02d}-{dd:02d}"
    except Exception:
        return ""


def to_dec(value):
    value = (str(value or "")).strip().translate(NP_DIGITS).replace(",", "")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return "bad"


def plain(v):
    """Decimal → फारममा देखाउने '12345.5' (खाली भए '')."""
    if v is None or v == "":
        return ""
    v = D(v)
    return f"{v:f}".rstrip("0").rstrip(".") if "." in f"{v:f}" else f"{v:f}"


class Form:
    """सानो फारम सहायक: मान पढ्ने, त्रुटि जम्मा गर्ने."""

    def __init__(self, request):
        self.post = request.POST
        self.errors = []

    def text(self, name, label, required=True):
        v = (self.post.get(name) or "").strip()
        if required and not v:
            self.errors.append(f"{label} भर्नुहोस्।")
        return v

    def amount(self, name, label, required=True, positive=True):
        v = to_dec(self.post.get(name))
        if v == "bad":
            self.errors.append(f"{label}: अङ्क मात्र लेख्नुहोस्।")
            return None
        if v is None:
            if required:
                self.errors.append(f"{label} भर्नुहोस्।")
            return None if required else ZERO
        if v < 0 or (positive and required and v == 0):
            self.errors.append(f"{label} ० भन्दा बढी हुनुपर्छ।")
        return v

    def day(self, name, label, required=True):
        raw = (self.post.get(name) or "").strip()
        if not raw:
            if required:
                self.errors.append(f"{label} भर्नुहोस्।")
            return None
        d = to_ad(raw)
        if d is None:
            self.errors.append(f"{label} मिलेन (वि.सं. YYYY-MM-DD)।")
        return d


def _user_wards(user):
    from usercommittee.views_workflow import _user_wards as uw

    return uw(user)


def _scoped(request):
    qs = workflow_queryset()
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    return qs, wards


def _project(request, project_id):
    qs, _ = _scoped(request)
    return get_object_or_404(qs, id=project_id)


def _guard(request, perm):
    if not has_perm(request.user, perm):
        messages.error(request, "यो काम गर्ने अनुमति तपाईंलाई छैन।")
        return redirect("bid_workflow")
    return None


def with_open(url, project_id):
    from urllib.parse import parse_qsl, urlencode

    parts = urlparse(url)
    if parts.path.rstrip("/") != reverse("bid_workflow").rstrip("/"):
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "open"]
    q.append(("open", str(project_id)))
    return parts.path + "?" + urlencode(q)


def _next(request, project):
    """सुरक्षित गरेपछि जाने ठाउँ: ?next= नभए कार्यप्रवाह (यही योजना खुला)."""
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) and nxt.startswith("/"):
        return nxt
    return with_open(reverse("bid_workflow"), project.id)


def _render_form(request, project, ctx):
    bid = current_bid(project)
    base = {
        "project": project, "bid": bid, "next": request.POST.get("next") or request.GET.get("next", ""),
        "back": _next(request, project), "below": pct_below(bid.total_cost_estimate, bid.bidding_amount) if bid else None,
    }
    if ctx.get("script") in ("running", "final") or ctx.get("icon") == "wallet":   # भुक्तानी फारम
        from projects.budget import budget_note
        ctx["note"] = (ctx.get("note", "") + " · " if ctx.get("note") else "") + budget_note(project)
    return render(request, "biddings/wf_form.html", base | ctx)


def F(name, label, value="", kind="text", required=True, hint="", readonly=False, wide=False, attrs="", options=None):
    return {"name": name, "label": label, "value": value, "kind": kind, "required": required, "hint": hint,
            "readonly": readonly, "wide": wide, "attrs": attrs, "options": options or []}


# ---------------------------------------------------------------- सूची र panel
@login_required
def workflow_list(request):
    if not has_perm(request.user, "bid.view"):
        return redirect("unauthorized")
    qs, wards = _scoped(request)
    q = request.GET.get("q", "").strip()
    ward = request.GET.get("ward", "")
    from projects.fiscal import default_fy_param

    fy = default_fy_param(request)   # पूर्वनिर्धारित: चालु आ.व.
    stage = request.GET.get("stage", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(address__icontains=q) | Q(biddings__bidder_name_nepali__icontains=q)
                       | Q(biddings__bidding_number__icontains=q)).distinct()
    if ward.isdigit():
        qs = qs.filter(ward_id=ward)
    if fy.isdigit():
        qs = qs.filter(fiscalyear_id=fy)

    rows = []
    counts = {"all": 0, "running": 0, "overdue": 0, "completed": 0, "to_approve": 0, "pg_alert": 0}
    approver = can_approve(request.user)
    for project in qs:
        steps, summary = bid_workflow(project, request.user)
        counts["all"] += 1
        counts["completed" if summary["completed"] else "running"] += 1
        counts["overdue"] += summary["overdue"]
        alert = summary["pg_alert"] or summary["apg_alert"]
        counts["pg_alert"] += alert
        waiting_me = approver and summary["current_key"] == "approval"
        counts["to_approve"] += waiting_me
        if (stage == "running" and summary["completed"]) or (stage == "completed" and not summary["completed"]) \
                or (stage == "overdue" and not summary["overdue"]) or (stage == "to_approve" and not waiting_me) \
                or (stage == "pg_alert" and not alert):
            continue
        if stage and stage not in ("running", "completed", "overdue", "to_approve", "pg_alert") \
                and summary["current_key"] != stage:
            continue
        rows.append({"project": project, "steps": steps, "cells": row_cells(steps), "summary": summary,
                     "waiting_me": waiting_me})

    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    per_page = per_page if per_page in (10, 25, 50, 100) else 25
    page = Paginator(rows, per_page).get_page(request.GET.get("page"))
    page_rows = list(page.object_list)

    open_id = request.GET.get("open", "")
    open_id = int(open_id) if open_id.isdigit() else None
    if open_id and not any(r["project"].id == open_id for r in page_rows):
        row = next((r for r in rows if r["project"].id == open_id), None)
        if row is None:
            project = _scoped(request)[0].filter(id=open_id).first()
            if project is not None:
                steps, summary = bid_workflow(project, request.user)
                row = {"project": project, "steps": steps, "cells": row_cells(steps), "summary": summary,
                       "waiting_me": approver and summary["current_key"] == "approval"}
        if row is not None:
            page_rows.insert(0, row)
        else:
            open_id = None

    keep = request.GET.copy()
    keep.pop("page", None)
    keep.pop("open", None)
    path = request.get_full_path()
    return render(request, "biddings/workflow.html", {
        "page": page, "rows": page_rows, "open_id": open_id, "columns": COLUMNS, "counts": counts,
        "wards": Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all(),
        "fiscal_years": FiscalYear.objects.all().order_by("-name"),
        "f": {"q": q, "ward": ward, "fiscalyear": fy, "stage": stage, "per_page": per_page},
        "keep_qs": keep.urlencode(), "return_to": path, "is_approver": approver,
    })


def _return_to(request):
    current = urlparse(request.headers.get("HX-Current-URL", ""))
    if current.path:
        return current.path + ("?" + current.query if current.query else "")
    return reverse("bid_workflow")


@login_required
def workflow_detail(request, project_id):
    if not has_perm(request.user, "bid.view"):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>अनुमति छैन।</div>", status=403)
    project = _project(request, project_id)
    steps, summary = bid_workflow(project, request.user)
    from projects.fiscal import lock_steps, old_message

    fy_locked = lock_steps(project, steps)
    with_next(steps, summary["extras"], with_open(_return_to(request), project.id))
    focus = request.GET.get("step")
    return render(request, "biddings/_workflow_detail.html", {
        "project": project, "steps": steps, "summary": summary,
        "fy_locked": fy_locked, "fy_lock_msg": old_message(project) if fy_locked else "", "x": summary["extras"],
        "focus": int(focus) if focus and focus.isdigit() else summary["current"],
    })


# ---------------------------------------------------------------- १. लागत अनुमान र बोलपत्र आह्वान
@login_required
def notice(request, project_id):
    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    if bid is not None and hasattr(bid, "approval"):
        messages.error(request, "स्वीकृत भइसकेको ठेक्काको आह्वान विवरण बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    from projects.procurement import plan_gate
    if bid is None and (gate := plan_gate(project)):
        messages.error(request, gate)
        return redirect("app_plan", project.id)
    errors = []
    if request.method == "POST":
        f = Form(request)
        number = f.text("bidding_number", "ठेक्का नम्बर")
        budget = f.amount("budget", "विनियोजित रकम")
        vat = f.amount("cost_estimate_vat", "भ्याट सहितको लागत अनुमान")
        ps = f.amount("ps_amount", "पि.एस. रकम", required=False, positive=False)
        cont = f.amount("contingency_amount", "कन्टिन्जेन्सी रकम", required=False, positive=False)
        published = f.day("bid_published_date", "सूचना प्रकाशित मिति")
        opening = f.day("bid_opening_date", "बोलपत्र खोल्ने मिति", required=False)
        errors = f.errors
        if published and opening and opening < published:
            errors.append("बोलपत्र खोल्ने मिति सूचना प्रकाशितभन्दा अघि हुन सक्दैन।")
        if number and SealedBid.objects.filter(bidding_number=number).exclude(id=getattr(bid, "id", None)).exists():
            errors.append(f"ठेक्का नम्बर “{number}” अर्को ठेक्कामा प्रयोग भइसकेको छ।")
        if not errors:
            total = (vat or ZERO) + (ps or ZERO)
            obj = bid or SealedBid(project=project, status=0)
            obj.bidding_number, obj.budget = number, budget
            obj.cost_estimate_vat, obj.ps_amount, obj.contingency_amount = vat, ps or ZERO, cont or ZERO
            obj.total_cost_estimate = total
            obj.bid_published_date, obj.bid_opening_date = published, opening
            obj.save()
            if project.status == 0:
                project.status = 1
                project.save(update_fields=["status"])
            if total > budget:
                messages.warning(request, f"लागत अनुमान (रु. {money(total)}) विनियोजित रकम (रु. {money(budget)}) भन्दा बढी छ।")
            messages.success(request, f"“{project.name}” को बोलपत्र आह्वान विवरण सुरक्षित भयो।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    from projects.procurement import contingency_amount, contingency_pct

    contingency_default = plain(contingency_amount("bid", project.budget)) if project.budget else ""
    return _render_form(request, project, {
        "title": "लागत अनुमान र बोलपत्र आह्वान", "icon": "bullhorn", "errors": errors,
        "submit": "सुरक्षित गर्नुहोस्", "script": "estimate",
        "sections": [
            {"title": "लागत अनुमान", "icon": "calculator", "fields": [
                F("budget", "विनियोजित रकम (रु.)", v("budget", plain(bid.budget) if bid else plain(project.budget)),
                  attrs="data-calc"),
                F("contingency_amount", "कन्टिन्जेन्सी रकम (रु.)",
                  v("contingency_amount", plain(bid.contingency_amount) if bid else contingency_default), required=False,
                  hint=f"विनियोजनको {np(contingency_pct('bid').normalize())}% (सेटिङअनुसार) सुझाव", attrs="data-calc"),
                F("cost_estimate_vat", "भ्याट सहितको लागत अनुमान (रु.)", v("cost_estimate_vat", plain(bid.cost_estimate_vat) if bid else ""),
                  attrs="data-calc"),
                F("ps_amount", "पि.एस. (Provisional Sum) रकम (रु.)", v("ps_amount", plain(bid.ps_amount) if bid else ""),
                  required=False, attrs="data-calc"),
                F("total_cost_estimate", "कुल लागत अनुमान (रु.)", plain(bid.total_cost_estimate) if bid else "",
                  readonly=True, required=False, hint="भ्याट सहितको लागत + पि.एस."),
            ]},
            {"title": "बोलपत्र आह्वान", "icon": "bullhorn", "fields": [
                F("bidding_number", "ठेक्का नम्बर", v("bidding_number", bid.bidding_number if bid else "")),
                F("bid_published_date", "सूचना प्रकाशित मिति", v("bid_published_date", to_bs(bid.bid_published_date) if bid else ""),
                  kind="date"),
                F("bid_opening_date", "बोलपत्र खोल्ने मिति", v("bid_opening_date", to_bs(bid.bid_opening_date) if bid else ""),
                  kind="date", required=False),
            ]},
        ],
    })


# ---------------------------------------------------------------- २. बोलपत्र मूल्याङ्कन
@login_required
def evaluation(request, project_id):
    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    if bid is None:
        messages.error(request, "पहिले बोलपत्र आह्वान विवरण भर्नुहोस्।")
        return redirect(_next(request, project))
    if hasattr(bid, "approval"):
        messages.error(request, "स्वीकृत भइसकेको बोलपत्रको मूल्याङ्कन बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    errors = []
    if request.method == "POST":
        f = Form(request)
        name = f.text("bidder_name_nepali", "निर्माण व्यवसायीको नाम")
        eng = f.text("bidder_name_english", "नाम (अङ्ग्रेजी)", required=False)
        owner = f.text("bidder_owner_nepali", "प्रोप्राइटर / सञ्चालक")
        addr = f.text("bidder_address_nepali", "ठेगाना")
        pan = f.text("bidder_pan", "PAN / VAT", required=False)
        amount = f.amount("bidding_amount", "कबोल रकम")
        evaluated = f.day("bid_evaluation_date", "मूल्याङ्कन मिति")
        errors = f.errors
        from projects import firms as fm
        if pan and not (pan.isdigit() and len(pan) == 9):
            errors.append("PAN / VAT नम्बर ९ अङ्कको हुनुपर्छ।")
        existing = fm.find(name, pan) if name else None
        if name and (e := fm.blocked(existing, name, pan)):
            errors.append(e)
        elif (e := fm.capacity_problem(existing, project)):
            errors.append(e)
        if evaluated and bid.bid_opening_date and evaluated < bid.bid_opening_date:
            errors.append("मूल्याङ्कन मिति बोलपत्र खोलेको मितिभन्दा अघि हुन सक्दैन।")
        if not errors:
            bid.bidder_name_nepali, bid.bidder_name_english = name, eng or None
            bid.bidder_owner_nepali, bid.bidder_address_nepali = owner, addr
            bid.bidding_amount, bid.bid_evaluation_date = amount, evaluated
            bid.status = max(bid.status, 1)
            bid.firm = fm.find_or_create(name, pan, addr, owner, kind="contractor")
            bid.save()
            if bid.total_cost_estimate and amount > bid.total_cost_estimate:
                messages.warning(request, "कबोल रकम लागत अनुमानभन्दा बढी छ — स्वीकृत गर्नुअघि कारण खुलाउनुहोस्।")
            messages.success(request, f"“{project.name}” को मूल्याङ्कन सुरक्षित भयो। अब आशयको सूचना छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    from projects import firms as fm
    return _render_form(request, project, {
        "firm_options": fm.options(["contractor"]),
        "title": "बोलपत्र मूल्याङ्कन", "icon": "scale-balanced", "errors": errors, "submit": "सुरक्षित गर्नुहोस्",
        "script": "below", "estimate": bid.total_cost_estimate,
        "sections": [
            {"title": "छनोट भएको (सारभूत रूपमा प्रभावग्राही न्यूनतम) बोलपत्रदाता", "icon": "user-tie", "fields": [
                F("bidder_name_nepali", "निर्माण व्यवसायीको नाम", v("bidder_name_nepali", bid.bidder_name_nepali or ""),
                  attrs='list="firm-options" autocomplete="off"', hint="फर्म दर्ताबाट छान्नुहोस् — नभए आफैँ दर्ता हुन्छ"),
                F("bidder_pan", "PAN / VAT नं.", v("bidder_pan", bid.firm.firm_pan if bid.firm_id else ""), required=False),
                F("bidder_name_english", "नाम (अङ्ग्रेजी)", v("bidder_name_english", bid.bidder_name_english or ""), required=False),
                F("bidder_owner_nepali", "प्रोप्राइटर / सञ्चालक", v("bidder_owner_nepali", bid.bidder_owner_nepali or "")),
                F("bidder_address_nepali", "ठेगाना", v("bidder_address_nepali", bid.bidder_address_nepali or "")),
            ]},
            {"title": "कबोल र मूल्याङ्कन", "icon": "scale-balanced", "fields": [
                F("bidding_amount", "कबोल रकम (भ्याट सहित, रु.)", v("bidding_amount", plain(bid.bidding_amount)),
                  attrs="data-calc"),
                F("below_pct", "लागत अनुमानभन्दा घटी (%)", "", readonly=True, required=False,
                  hint=f"लागत अनुमान रु. {money(bid.total_cost_estimate)}"),
                F("bid_evaluation_date", "मूल्याङ्कन मिति", v("bid_evaluation_date", to_bs(bid.bid_evaluation_date)),
                  kind="date"),
            ]},
        ],
    })


# ---------------------------------------------------------------- ३. रुजु / स्वीकृत (modal)
def _approve_ctx(project, bid):
    problems, warnings = [], []
    if bid is None or not (bid.bidder_name_nepali and bid.bidding_amount):
        problems.append("बोलपत्र मूल्याङ्कन बाँकी छ।")
    asay = bid.prints.filter(doc_type="asay").first() if bid else None
    if bid is not None and not hasattr(bid, "approval"):
        if asay is None:
            warnings.append("आशयको सूचना छापिएको अभिलेख छैन।")
        elif (date.today() - asay.printed_at.date()).days < INTENT_DAYS:
            left = INTENT_DAYS - (date.today() - asay.printed_at.date()).days
            warnings.append(f"आशयको सूचनाको {np(INTENT_DAYS)} दिने उजुरी अवधि सकिन {np(left)} दिन बाँकी छ।")
        if bid.total_cost_estimate and bid.bidding_amount and bid.bidding_amount > bid.total_cost_estimate:
            warnings.append("कबोल रकम लागत अनुमानभन्दा बढी छ।")
        if bid.bidding_amount and (w := over_budget_warning(project, bid.bidding_amount, "कबोल रकम")):
            warnings.append(w)
    return {"project": project, "bid": bid, "problems": problems, "warnings": warnings,
            "approval": getattr(bid, "approval", None) if bid else None,
            "below": pct_below(bid.total_cost_estimate, bid.bidding_amount) if bid else None,
            "pg": suggested_pg(bid) if bid and bid.bidding_amount else None,
            "asay_bs": bs_date(asay.printed_at.date()) if asay else "",
            "dates": [(lbl, bs_date(getattr(bid, k))) for lbl, k in (
                ("सूचना प्रकाशित", "bid_published_date"), ("बोलपत्र खोलेको", "bid_opening_date"),
                ("मूल्याङ्कन", "bid_evaluation_date"))] if bid else []}


@login_required
def approve(request, project_id):
    project = _project(request, project_id)
    bid = current_bid(project)
    allowed = can_approve(request.user)
    if not allowed and not (bid and hasattr(bid, "approval") and has_perm(request.user, "bid.view")):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>तपाईंलाई बोलपत्र स्वीकृत गर्ने अधिकार छैन।</div>",
                            status=403)
    ctx = _approve_ctx(project, bid)
    if request.method == "POST":
        if not allowed:
            return HttpResponse("<p class='text-sm text-rose-600'>स्वीकृत गर्ने अधिकार छैन।</p>", status=403)
        if ctx["approval"] is not None:
            return HttpResponse("<p class='text-sm text-rose-600'>पहिले नै स्वीकृत भइसकेको छ।</p>", status=400)
        if ctx["problems"]:
            return HttpResponse("<p class='text-sm text-rose-600'>" + " ".join(ctx["problems"]) + "</p>", status=400)
        name, post = approver_identity(request.user, "municipal")
        with transaction.atomic():
            BidApproval.objects.create(sealed_bid=bid, approved_by=request.user, approver_name=name,
                                       approver_post=post, remarks=request.POST.get("remarks", "").strip())
            bid.status = max(bid.status, 2)
            bid.save(update_fields=["status"])
        messages.success(request, f"“{project.name}” को बोलपत्र स्वीकृत भयो। अब PG माग र सम्झौताको सूचना पठाउनुहोस्।")
        response = HttpResponse(status=204)
        response["HX-Redirect"] = with_open(_return_to(request), project.id)
        return response
    name, post = approver_identity(request.user, "municipal")
    return render(request, "biddings/_approve_modal.html", ctx | {"can_approve": allowed, "name": name, "post": post})


# ---------------------------------------------------------------- ४. स्वीकृति र PG माग
@login_required
def acceptance(request, project_id):
    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    contract, bond, req, *_ = contract_parts(bid)
    if bid is None or not (hasattr(bid, "approval") or contract or req):
        messages.error(request, "PG माग अघि बोलपत्र रुजु / स्वीकृत हुनुपर्छ।")
        return redirect(_next(request, project))
    if bond is not None:
        messages.error(request, "सम्झौता भइसकेपछि PG माग बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    errors = []
    suggestion = suggested_pg(bid)
    if request.method == "POST":
        f = Form(request)
        approved = f.day("bid_approved_date", "स्वीकृत मिति")
        amount = f.amount("required_amount", "कार्यसम्पादन जमानत रकम")
        expiry = f.day("required_expiry_date", "जमानतको न्यूनतम म्याद")
        errors = f.errors
        if approved and expiry and expiry <= approved:
            errors.append("जमानतको म्याद स्वीकृत मितिभन्दा पछि हुनुपर्छ।")
        if not errors:
            obj = req or PerformanceBondRequirement(sealed_bid=bid)
            obj.bid_approved_date, obj.required_amount, obj.required_expiry_date = approved, amount, expiry
            obj.save()
            bid.status = max(bid.status, 2)
            bid.save(update_fields=["status"])
            if amount < suggestion:
                messages.warning(request, f"PG रकम नियमअनुसारको सुझाव (रु. {money(suggestion)}) भन्दा कम छ।")
            messages.success(request, "PG माग सुरक्षित भयो। अब स्वीकृति टिप्पणी र सम्झौता गर्न आउने सूचना छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    appr = getattr(bid, "approval", None)
    return _render_form(request, project, {
        "title": "स्वीकृति टिप्पणी र कार्यसम्पादन जमानत (PG) माग", "icon": "file-signature", "errors": errors,
        "submit": "सुरक्षित गर्नुहोस्",
        "note": f"नियमअनुसार सुझाव: कबोल रकमको ५% (कबोल लागत अनुमानको ८५% भन्दा कम भए थप) = रु. {money(suggestion)}",
        "sections": [{"title": "PG माग", "icon": "building-columns", "fields": [
            F("bid_approved_date", "बोलपत्र स्वीकृत मिति",
              v("bid_approved_date", to_bs(req.bid_approved_date) if req else to_bs(appr.approved_at.date()) if appr else ""),
              kind="date"),
            F("required_amount", "कार्यसम्पादन जमानत रकम (रु.)",
              v("required_amount", plain(req.required_amount) if req else plain(suggestion))),
            F("required_expiry_date", "जमानतको न्यूनतम म्याद (मिति)",
              v("required_expiry_date", to_bs(req.required_expiry_date) if req else ""), kind="date",
              hint="सामान्यतया काम सम्पन्न + त्रुटि सच्याउने अवधि + १ महिना"),
        ]}],
    })


# ---------------------------------------------------------------- ५. सम्झौता र PG (बैंक जमानत)
@login_required
def agreement(request, project_id):
    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    contract, bond, req, *_ = contract_parts(bid)
    if bid is None or req is None:
        messages.error(request, "सम्झौता अघि PG माग विवरण चाहिन्छ।")
        return redirect(_next(request, project))
    if bond is not None:
        messages.error(request, "सम्झौता र PG पहिले नै दर्ता भइसकेको छ। म्याद थप्न ‘म्याद थप’ प्रयोग गर्नुहोस्।")
        return redirect(_next(request, project))
    errors = []
    if request.method == "POST":
        f = Form(request)
        c_date = f.day("contract_date", "सम्झौता मिति")
        c_end = f.day("contract_expire_date", "काम सम्पन्न गर्नुपर्ने मिति")
        bank = f.text("bank_name", "जमानत दिने बैंक")
        number = f.text("bond_number", "जमानत नम्बर")
        amount = f.amount("issued_amount", "जमानत रकम")
        issue = f.day("issue_date", "जमानत जारी मिति")
        expiry = f.day("expiry_date", "जमानतको म्याद")
        errors = f.errors
        if c_date and c_end and c_end <= c_date:
            errors.append("काम सम्पन्न गर्नुपर्ने मिति सम्झौता मितिभन्दा पछि हुनुपर्छ।")
        if c_date and req.bid_approved_date and c_date < req.bid_approved_date:
            errors.append("सम्झौता मिति बोलपत्र स्वीकृत मितिभन्दा अघि हुन सक्दैन।")
        if amount is not None and req.required_amount and amount < req.required_amount:
            errors.append(f"जमानत रकम माग गरिएको रु. {money(req.required_amount)} भन्दा कम छ।")
        if expiry and req.required_expiry_date and expiry < req.required_expiry_date:
            errors.append(f"जमानतको म्याद माग गरिएको {bs_date(req.required_expiry_date)} भन्दा अघि सकिन्छ।")
        if expiry and c_end and expiry < c_end:
            errors.append("जमानतको म्याद काम सम्पन्न गर्नुपर्ने मितिभन्दा पछिसम्म हुनुपर्छ।")
        if issue and expiry and expiry <= issue:
            errors.append("जमानतको म्याद जारी मितिभन्दा पछि हुनुपर्छ।")
        if not errors:
            with transaction.atomic():
                c = contract or Contract(sealed_bid=bid)
                c.contract_date, c.contract_expire_date = c_date, c_end
                c.save()
                PerformanceBondIssued.objects.create(contract=c, bank_name=bank, bond_number=number, issued_amount=amount,
                                                     issue_date=issue, expiry_date=expiry,
                                                     document=request.FILES.get("document"))
                bid.status = 3
                bid.save(update_fields=["status"])
            messages.success(request, "सम्झौता र कार्यसम्पादन जमानत दर्ता भयो। अब सम्झौता पत्र र कार्यादेश छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    return _render_form(request, project, {
        "title": "सम्झौता र कार्यसम्पादन जमानत", "icon": "handshake", "errors": errors, "upload": True,
        "submit": "सुरक्षित गर्नुहोस्",
        "note": f"माग गरिएको PG: रु. {money(req.required_amount)}, म्याद कम्तीमा {bs_date(req.required_expiry_date)} सम्म",
        "sections": [
            {"title": "सम्झौता", "icon": "file-contract", "fields": [
                F("contract_date", "सम्झौता मिति", v("contract_date"), kind="date"),
                F("contract_expire_date", "काम सम्पन्न गर्नुपर्ने मिति", v("contract_expire_date"), kind="date"),
            ]},
            {"title": "कार्यसम्पादन जमानत (बैंक ग्यारेन्टी)", "icon": "building-columns", "fields": [
                F("bank_name", "जमानत दिने बैंक", v("bank_name")),
                F("bond_number", "जमानत नम्बर", v("bond_number")),
                F("issued_amount", "जमानत रकम (रु.)", v("issued_amount", plain(req.required_amount))),
                F("issue_date", "जारी मिति", v("issue_date"), kind="date"),
                F("expiry_date", "म्याद (मिति)", v("expiry_date", to_bs(req.required_expiry_date)), kind="date"),
                F("document", "जमानतको स्क्यान (ऐच्छिक)", kind="file", required=False, hint="PDF वा फोटो"),
            ]},
        ],
    })


# ---------------------------------------------------------------- ऐच्छिक: अग्रिम भुक्तानी
@login_required
def advance(request, project_id):
    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    contract, bond, _req, final, advances, _runs = contract_parts(bid)
    if bond is None or final is not None:
        messages.error(request, "अग्रिम भुक्तानी सम्झौतापछि र अन्तिम बिलअघि मात्र।")
        return redirect(_next(request, project))
    contract_amount = D(bid.bidding_amount)
    paid = sum((D(a.approved_amount) for a in advances), ZERO)
    errors = []
    if request.method == "POST":
        f = Form(request)
        amount = f.amount("approved_amount", "अग्रिम रकम")
        approved = f.day("approval_date", "स्वीकृत मिति")
        bank = f.text("bank_name", "जमानत दिने बैंक")
        number = f.text("guarantee_number", "जमानत नम्बर")
        g_amount = f.amount("guaranteed_amount", "जमानत रकम")
        issue = f.day("issue_date", "जमानत जारी मिति")
        expiry = f.day("expiry_date", "जमानतको म्याद")
        remarks = f.text("remarks", "कैफियत", required=False)
        errors = f.errors
        if amount is not None and paid + amount > contract_amount:
            errors.append("कुल अग्रिम भुक्तानी ठेक्का रकमभन्दा बढी हुन सक्दैन।")
        if amount is not None and (e := check_payment(project, budget_spent(project) + amount, "यो अग्रिम")):
            errors.append(e)
        if amount is not None and g_amount is not None and g_amount < amount:
            errors.append("अग्रिम भुक्तानी जमानत रकम अग्रिम रकमभन्दा कम हुन सक्दैन।")
        if issue and expiry and expiry <= issue:
            errors.append("जमानतको म्याद जारी मितिभन्दा पछि हुनुपर्छ।")
        if approved and contract.contract_date and approved < contract.contract_date:
            errors.append("अग्रिम स्वीकृत मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if not errors:
            with transaction.atomic():
                ap = AdvancePayment.objects.create(contract=contract, approved_amount=amount, approval_date=approved,
                                                   remarks=remarks)
                AdvanceBankGuarantee.objects.create(advance_payment=ap, bank_name=bank, guarantee_number=number,
                                                    guaranteed_amount=g_amount, issue_date=issue, expiry_date=expiry,
                                                    document=request.FILES.get("document"))
            if contract_amount and (paid + amount) > contract_amount * Decimal("0.2"):
                messages.warning(request, "कुल अग्रिम ठेक्का रकमको २०% भन्दा बढी भयो — सम्झौताको शर्त जाँच्नुहोस्।")
            messages.success(request, f"अग्रिम भुक्तानी रु. {money(amount)} दर्ता भयो। टिप्पणी कार्यप्रवाहबाट छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    return _render_form(request, project, {
        "title": "अग्रिम भुक्तानी (मोबिलाइजेसन पेश्की)", "icon": "wallet", "errors": errors, "upload": True,
        "submit": "सुरक्षित गर्नुहोस्",
        "note": f"ठेक्का रकम रु. {money(contract_amount)} · दिइसकेको अग्रिम रु. {money(paid)} · "
                f"सामान्य सीमा २०% = रु. {money(contract_amount * Decimal('0.2'))}",
        "sections": [
            {"title": "अग्रिम भुक्तानी", "icon": "money-bill-wave", "fields": [
                F("approved_amount", "अग्रिम रकम (रु.)", v("approved_amount")),
                F("approval_date", "स्वीकृत मिति", v("approval_date", to_bs(date.today())), kind="date"),
                F("remarks", "कैफियत", v("remarks"), required=False),
            ]},
            {"title": "अग्रिम भुक्तानी जमानत (बैंक ग्यारेन्टी)", "icon": "building-columns", "fields": [
                F("bank_name", "बैंक", v("bank_name", bond.bank_name)),
                F("guarantee_number", "जमानत नम्बर", v("guarantee_number")),
                F("guaranteed_amount", "जमानत रकम (रु.)", v("guaranteed_amount"), hint="अग्रिम रकम बराबर वा बढी"),
                F("issue_date", "जारी मिति", v("issue_date"), kind="date"),
                F("expiry_date", "म्याद (मिति)", v("expiry_date", to_bs(contract.current_expiry_date)), kind="date"),
                F("document", "जमानतको स्क्यान (ऐच्छिक)", kind="file", required=False),
            ]},
        ],
    })


# ---------------------------------------------------------------- ऐच्छिक: म्याद थप (ऐन दफा ५६)
@login_required
def extension(request, project_id):
    from projects.models import ProcurementLimits

    from .contracts import ld_deadline
    from .models import ContractExtension, PerformanceBondExtension

    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    contract, bond, _req, final, _adv, _runs = contract_parts(bid)
    if bond is None or final is not None:
        messages.error(request, "म्याद थप सम्झौतापछि र अन्तिम बिलअघि मात्र।")
        return redirect(_next(request, project))
    L = ProcurementLimits.get()
    current = contract.current_expiry_date
    errors = []
    if request.method == "POST":
        f = Form(request)
        applied = f.day("applied_on", "निवेदन मिति")
        new_exp = f.day("extended_expiry_date", "नयाँ म्याद")
        kind = f.text("kind", "म्याद थपको प्रकार")
        reason = f.text("reason", "कारण")
        detail = f.text("remarks", "कारणको विवरण")
        ref = f.text("decision_ref", "निर्णय नं. / मिति")
        pg_new = f.day("pg_expiry_date", "PG को नयाँ म्याद", required=False)
        late_ok = bool(request.POST.get("late_ok"))
        errors = f.errors
        if kind and kind not in dict(ContractExtension.KINDS):
            errors.append("म्याद थपको प्रकार मिलेन।")
        if reason and reason not in dict(ContractExtension.REASONS):
            errors.append("कारण मिलेन।")
        if kind == "excusable" and reason == "contractor":
            errors.append("निर्माण व्यवसायीको कारणले भएको ढिलाइमा “हर्जाना सहित” म्याद थप मात्र।")
        if new_exp and current and new_exp <= current:
            errors.append(f"नयाँ म्याद हालको म्याद ({bs_date(current)}) भन्दा पछि हुनुपर्छ।")
        if applied and current and (current - applied).days < L.extension_notice_days and not late_ok:
            errors.append(f"निवेदन म्याद सकिनुभन्दा कम्तीमा {np(L.extension_notice_days)} दिन अघि पर्नुपर्छ — "
                          "ढिलो निवेदन स्वीकार गर्ने भए कारणसहित “ढिलो निवेदन स्वीकार” छान्नुहोस्।")
        need_pg = new_exp and bond.current_expiry_date and bond.current_expiry_date < new_exp
        if need_pg and not pg_new:
            errors.append(f"PG को म्याद ({bs_date(bond.current_expiry_date)}) नयाँ सम्झौता म्यादभन्दा अघि सकिन्छ — PG को नयाँ म्याद भर्नुहोस्।")
        if pg_new and new_exp and pg_new < new_exp:
            errors.append("PG को म्याद सम्झौताको नयाँ म्यादभन्दा पछिसम्म हुनुपर्छ।")
        if not errors:
            from usercommittee.workflow import approver_identity

            name, post = approver_identity(request.user, "municipal")
            with transaction.atomic():
                ContractExtension.objects.create(contract=contract, previous_expiry_date=current, extended_expiry_date=new_exp,
                                                 remarks=detail + (" (ढिलो निवेदन स्वीकार)" if late_ok else ""),
                                                 kind=kind, reason=reason, applied_on=applied, decision_ref=ref,
                                                 document=request.FILES.get("document"), approver_name=f"{name} ({post})")
                if pg_new and pg_new > bond.current_expiry_date:
                    PerformanceBondExtension.objects.create(bond=bond, previous_expiry_date=bond.current_expiry_date,
                                                            extended_expiry_date=pg_new, remarks=detail)
            days = (new_exp - current).days
            messages.success(request, f"म्याद {np(days)} दिन थपियो ({bs_date(new_exp)} सम्म) — "
                                      + ("ढिलाइ हर्जाना बिना।" if kind == "excusable" else "ढिलाइ हर्जाना सहित।"))
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    exts = list(contract.extensions.all())
    hist = " · ".join(f"{bs_date(e.previous_expiry_date)} → {bs_date(e.extended_expiry_date)}"
                      + (" (हर्जाना सहित)" if e.kind == "penalty" else "") for e in exts)
    return _render_form(request, project, {
        "title": "म्याद थप (सम्झौता र PG)", "icon": "calendar-plus", "errors": errors, "upload": True,
        "submit": "म्याद थप गर्नुहोस्",
        "note": f"मूल म्याद {bs_date(contract.contract_expire_date)} · हालको म्याद {bs_date(current)} · "
                f"हर्जाना लाग्ने मिति {bs_date(ld_deadline(contract))} · PG म्याद {bs_date(bond.current_expiry_date)}"
                + (f" · अघिल्ला म्याद थप: {hist}" if hist else ""),
        "sections": [
            {"title": "निवेदन र कारण", "icon": "file-lines", "fields": [
                F("applied_on", "निर्माण व्यवसायीको निवेदन मिति", v("applied_on", to_bs(date.today())), kind="date",
                  hint=f"म्याद सकिनुभन्दा कम्तीमा {np(L.extension_notice_days)} दिन अघि"),
                F("reason", "कारण", v("reason"), kind="select", options=[("", "— छान्नुहोस् —")] + list(ContractExtension.REASONS)),
                F("kind", "म्याद थपको प्रकार", v("kind"), kind="select",
                  options=[("", "— छान्नुहोस् —")] + list(ContractExtension.KINDS)),
                F("remarks", "कारणको विवरण", v("remarks"), kind="textarea", wide=True),
                F("late_ok", "", v("late_ok"), kind="checkbox", required=False, wide=True,
                  hint="ढिलो निवेदन स्वीकार (कारण विवरणमा खुलाउने)"),
            ]},
            {"title": "नयाँ म्याद र निर्णय", "icon": "calendar-check", "fields": [
                F("extended_expiry_date", "सम्झौताको नयाँ म्याद", v("extended_expiry_date"), kind="date"),
                F("pg_expiry_date", "PG को नयाँ म्याद", v("pg_expiry_date"), kind="date", required=False,
                  hint="PG सम्झौताको नयाँ म्यादभन्दा पछिसम्म हुनुपर्छ"),
                F("decision_ref", "निर्णय नं. / मिति", v("decision_ref")),
                F("document", "निवेदन / निर्णय (स्क्यान)", kind="file", required=False),
            ]},
        ],
    })


# ---------------------------------------------------------------- ऐच्छिक: भेरिएसन आदेश (ऐन दफा ५४)
@login_required
def variation(request, project_id):
    from projects.models import ProcurementLimits

    from .contracts import authority_for, pct, revised_amount, variation_total
    from .models import VariationOrder

    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    contract, bond, _req, final, _adv, runs = contract_parts(bid)
    if bond is None or final is not None:
        messages.error(request, "भेरिएसन सम्झौतापछि र अन्तिम बिलअघि मात्र।")
        return redirect(_next(request, project))
    L = ProcurementLimits.get()
    base = D(bid.bidding_amount)
    so_far = variation_total(contract)
    last_cum = D(runs[-1].total_evaluated_amount) if runs else ZERO
    errors = []
    if request.method == "POST":
        f = Form(request)
        day_ = f.day("date", "स्वीकृत मिति")
        sign = request.POST.get("sign", "+")
        amount = f.amount("amount", "रकम")
        desc = f.text("description", "कामको विवरण / कारण")
        expert = f.text("expert_recommendation", "विज्ञ समूहको सिफारिस", required=False)
        ref = f.text("decision_ref", "निर्णय नं. / मिति")
        errors = f.errors
        if amount is not None:
            amount = -amount if sign == "-" else amount
            cum = so_far + amount
            cum_pct = pct(cum, base)
            if base + cum < last_cum:
                errors.append(f"घटाउँदा संशोधित रकम अहिलेसम्मको मूल्याङ्कन रु. {money(last_cum)} भन्दा कम हुन्छ।")
            if abs(cum_pct) > D(L.variation_office_pct):
                if not request.POST.get("higher_ok"):
                    errors.append(f"कुल भेरिएसन {np(cum_pct)}% — कार्यालय प्रमुखको सीमा {np(L.variation_office_pct)}% भन्दा बढी भयो। "
                                  f"{authority_for(cum_pct)} बाट स्वीकृत भएको भए “माथिल्लो निकायबाट स्वीकृत” छानी निर्णय संलग्न गर्नुहोस्।")
                elif not request.FILES.get("document"):
                    errors.append("माथिल्लो निकायको निर्णयको स्क्यान संलग्न गर्नुहोस्।")
        if day_ and contract.contract_date and day_ < contract.contract_date:
            errors.append("भेरिएसन मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if not errors:
            cum_pct = pct(so_far + amount, base)
            VariationOrder.objects.create(
                contract=contract, number=contract.variations.count() + 1, date=day_, amount=amount, description=desc,
                expert_recommendation=expert, decision_ref=ref, document=request.FILES.get("document"),
                authority=authority_for(cum_pct), created_by=request.user)
            messages.success(request, f"भेरिएसन रु. {money(amount)} स्वीकृत — संशोधित सम्झौता रकम रु. "
                                      f"{money(revised_amount(bid, contract))} (कुल {np(cum_pct)}%)।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    tiers = " · ".join(f"{np(c) + '%' if c else '१५% भन्दा बढी'}: {w}" for c, w in
                       [(Decimal("5"), "तृतीय श्रेणी"), (Decimal("10"), "द्वितीय श्रेणी"), (Decimal("15"), "प्रथम श्रेणी"),
                        (None, "विभागीय प्रमुख")])
    return _render_form(request, project, {
        "title": f"भेरिएसन आदेश नं. {np(contract.variations.count() + 1)}", "icon": "code-compare", "errors": errors,
        "upload": True, "submit": "भेरिएसन स्वीकृत गर्नुहोस्",
        "note": f"कबोल रकम रु. {money(base)} · अहिलेसम्मको भेरिएसन रु. {money(so_far)} ({np(pct(so_far, base))}%) · "
                f"संशोधित रकम रु. {money(base + so_far)} · स्वीकृत गर्ने अधिकारी (ऐन दफा ५४): {tiers}",
        "sections": [
            {"title": "भेरिएसन", "icon": "pen-ruler", "fields": [
                F("date", "स्वीकृत मिति", v("date", to_bs(date.today())), kind="date"),
                F("sign", "थप / घट", v("sign", "+"), kind="select", options=[("+", "थप (+)"), ("-", "घट (−)")]),
                F("amount", "रकम (रु.)", v("amount")),
                F("description", "कामको विवरण / कारण", v("description"), kind="textarea", wide=True,
                  hint="सम्झौता गर्दा पूर्वानुमान गर्न नसकिएको परिस्थिति खुलाउनुहोस्"),
                F("expert_recommendation", "विज्ञ समूहको सिफारिस", v("expert_recommendation"), kind="textarea", wide=True,
                  required=False),
            ]},
            {"title": "निर्णय", "icon": "stamp", "fields": [
                F("decision_ref", "निर्णय नं. / मिति", v("decision_ref")),
                F("document", "निर्णय (स्क्यान)", kind="file", required=False),
                F("higher_ok", "", v("higher_ok"), kind="checkbox", required=False,
                  hint=f"कार्यालय प्रमुखको सीमा ({np(L.variation_office_pct)}%) भन्दा बढी — माथिल्लो निकायबाट स्वीकृत"),
            ]},
        ],
    })


# ---------------------------------------------------------------- ऐच्छिक: रनिङ बिल
TAX_FIELDS = [("agrim_tax", "अग्रिम आयकर"), ("vat_deduction", "भ्याट कट्टी"), ("dharauti_deduction", "धरौटी कट्टी"),
              ("bahal_tax", "बहाल कर")]


@login_required
def running(request, project_id):
    if (r := _guard(request, "bid.manage")):
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    contract, bond, _req, final, advances, runs = contract_parts(bid)
    if bond is None or final is not None:
        messages.error(request, "रनिङ बिल सम्झौतापछि र अन्तिम बिलअघि मात्र।")
        return redirect(_next(request, project))
    contract_amount = D(bid.bidding_amount)
    prev_cum = D(runs[-1].total_evaluated_amount) if runs else ZERO
    adv_total = sum((D(a.approved_amount) for a in advances), ZERO)
    adv_adjusted = sum((D(r.advance_adjusted) for r in runs), ZERO)
    from projects import mb as mbk
    mbs = mbk.summary(project)
    errors = []
    if request.method == "POST":
        f = Form(request)
        day_ = f.day("evaluation_date", "मूल्याङ्कन मिति")
        cum = f.amount("total_evaluated_amount", "हालसम्मको कुल मूल्याङ्कन")
        payable = f.amount("payable_amount", "यस पटकको भुक्तानी योग्य रकम")
        adj = f.amount("advance_adjusted", "अग्रिम कट्टी", required=False, positive=False)
        taxes = {k: f.amount(k, lbl, required=False, positive=False) for k, lbl in TAX_FIELDS}
        remarks = f.text("remarks", "कैफियत", required=False)
        errors = f.errors
        if cum is not None:
            if cum <= prev_cum:
                errors.append(f"कुल मूल्याङ्कन अघिल्लो रनिङ (रु. {money(prev_cum)}) भन्दा बढी हुनुपर्छ।")
            from .contracts import revised_amount
            rev = revised_amount(bid, contract)
            if contract_amount and cum > rev + 1:
                errors.append(f"कुल मूल्याङ्कन संशोधित सम्झौता रकम रु. {money(rev)} भन्दा बढी — पहिले भेरिएसन आदेश स्वीकृत गर्नुहोस्।")
        if mbs["has"] and cum is not None and day_:
            mbv = mbk.value_upto(project, day_)
            if abs(cum - mbv) > 1 and not request.POST.get("mb_override"):
                errors.append(f"नापी किताबअनुसार {bs_date(day_)} सम्मको मूल्याङ्कन रु. {money(mbv)} — कुल मूल्याङ्कन त्यही हुनुपर्छ "
                              "(फरक राख्ने भए “नापी किताबभन्दा फरक” छानी कैफियतमा कारण लेख्नुहोस्)।")
            elif abs(cum - mbv) > 1 and not (request.POST.get("remarks") or "").strip():
                errors.append("नापी किताबभन्दा फरक रकम राख्दा कैफियतमा कारण लेख्नुहोस्।")
        if cum is not None and payable is not None and payable > cum - prev_cum:
            errors.append(f"यस पटकको भुक्तानी योग्य रकम यस पटकको काम (रु. {money(cum - prev_cum)}) भन्दा बढी भयो।")
        if adj and adj > adv_total - adv_adjusted:
            errors.append(f"अग्रिम कट्टी बाँकी अग्रिम (रु. {money(adv_total - adv_adjusted)}) भन्दा बढी भयो।")
        net = (payable or ZERO) - (adj or ZERO) - sum((t or ZERO for t in taxes.values()), ZERO)
        if not errors and net <= 0:
            errors.append("खुद भुक्तानी रकम ० भन्दा बढी हुनुपर्छ।")
        if not errors and (e := check_payment(project, budget_spent(project) + payable - (adj or ZERO), "यो रनिङ बिल")):
            errors.append(e)
        if day_ and runs and day_ < runs[-1].evaluation_date:
            errors.append("मूल्याङ्कन मिति अघिल्लो रनिङ बिलभन्दा अघि हुन सक्दैन।")
        if not errors:
            RunningEvaluation.objects.create(contract=contract, evaluation_date=day_, total_evaluated_amount=cum,
                                             payable_amount=payable, advance_adjusted=adj or ZERO,
                                             net_payable=net, remarks=remarks,
                                             **{k: (t or ZERO) for k, t in taxes.items()})
            if mbs["has"]:
                mbk.mark_billed(project, len(runs) + 1, day_)
            if contract_amount and cum > contract_amount:
                messages.warning(request, "कुल मूल्याङ्कन ठेक्का रकमभन्दा बढी भयो।")
            messages.success(request, f"रनिङ बिल नं. {len(runs) + 1} (खुद रु. {money(net)}) दर्ता भयो।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    adv_left = adv_total - adv_adjusted
    return _render_form(request, project, {
        "title": f"रनिङ बिल नं. {len(runs) + 1}", "icon": "file-invoice", "errors": errors, "script": "running",
        "submit": "सुरक्षित गर्नुहोस्", "prev_cum": prev_cum,
        "note": f"ठेक्का रकम रु. {money(contract_amount)} · अघिल्लो रनिङसम्मको मूल्याङ्कन रु. {money(prev_cum)} · "
                f"कट्टी गर्न बाँकी अग्रिम रु. {money(adv_left)}"
                + (f" · नापी किताबअनुसार हालसम्म रु. {money(mbs['value'])} (भौतिक प्रगति {np(mbs['progress'])}%)" if mbs["has"] else ""),
        "sections": [
            {"title": "मूल्याङ्कन", "icon": "ruler-combined", "fields": [
                F("evaluation_date", "मूल्याङ्कन मिति", v("evaluation_date", to_bs(date.today())), kind="date"),
                F("total_evaluated_amount", "हालसम्मको कुल मूल्याङ्कन (रु.)",
                  v("total_evaluated_amount", plain(mbs["value"]) if mbs["has"] and mbs["value"] > prev_cum else ""),
                  attrs="data-calc", hint="नापी किताबबाट (स्वतः)" if mbs["has"] else "सुरुदेखि यो रनिङसम्मको जम्मा"),
                F("payable_amount", "यस पटकको भुक्तानी योग्य रकम (रु.)", v("payable_amount"), attrs="data-calc",
                  hint="कुल मूल्याङ्कन − अघिल्लो मूल्याङ्कन (स्वतः)"),
                F("advance_adjusted", "अग्रिम कट्टी (रु.)", v("advance_adjusted", "0"), required=False, attrs="data-calc"),
            ]},
            {"title": "कर कट्टी", "icon": "receipt", "fields":
                [F(k, lbl + " (रु.)", v(k, "0"), required=False, attrs="data-calc") for k, lbl in TAX_FIELDS] + [
                F("net_payable", "खुद भुक्तानी (रु.)", "", readonly=True, required=False),
                F("remarks", "कैफियत", v("remarks"), required=False)]
                + ([F("mb_override", "", v("mb_override"), kind="checkbox", required=False, wide=True,
                      hint="नापी किताबभन्दा फरक रकम (कारण कैफियतमा)")] if mbs["has"] else [])},
        ],
    })


# ---------------------------------------------------------------- ६. अन्तिम बिल
@login_required
def final(request, project_id):
    if not has_perm(request.user, "uc.valuation") and (r := _guard(request, "bid.manage")):   # अन्तिम मूल्याङ्कन (इन्जिनियर) पनि
        return r
    project = _project(request, project_id)
    bid = current_bid(project)
    contract, bond, _req, fp, advances, runs = contract_parts(bid)
    if bond is None:
        messages.error(request, "अन्तिम बिल अघि सम्झौता र PG दर्ता चाहिन्छ।")
        return redirect(_next(request, project))
    if fp is not None and bid.prints.filter(doc_type="final_tippani").exists():
        messages.error(request, "अन्तिम टिप्पणी छापिइसकेकाले अन्तिम बिल बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    contract_amount = D(bid.bidding_amount)
    adv_total = sum((D(a.approved_amount) for a in advances), ZERO)
    run_net = sum((D(r.net_payable) for r in runs), ZERO)
    run_gross = sum((D(r.payable_amount) for r in runs), ZERO)
    adv_adjusted = sum((D(r.advance_adjusted) for r in runs), ZERO)
    last_cum = D(runs[-1].total_evaluated_amount) if runs else ZERO
    from projects import mb as mbk
    mbs = mbk.summary(project)
    errors = []
    if request.method == "POST":
        f = Form(request)
        total_eval = f.amount("total_evaluation_amount", "कुल मूल्याङ्कन रकम")
        taxes = {k: f.amount(k, lbl, required=False, positive=False) for k, lbl in TAX_FIELDS}
        paid_on = f.day("payment_date", "भुक्तानी मिति")
        remarks = f.text("remarks", "कैफियत", required=False)
        posted_final = f.amount("final_amount", "खुद भुक्तानी रकम", required=False, positive=False)
        done_on = f.day("completion_date", "काम सम्पन्न मिति", required=False) or paid_on   # खाली = भुक्तानी मिति
        ld_posted = (f.amount("ld_amount", "ढिलाइ हर्जाना", required=False, positive=False)
                     if (request.POST.get("ld_amount") or "").strip() else None)   # खाली = हिसाबअनुसार
        ld_note = f.text("ld_note", "हर्जाना कम/छुटको कारण", required=False)
        errors = f.errors
        from .contracts import compute_ld
        ld_days, ld_calc, ld_last, _rate, ld_cap = compute_ld(bid, contract, done_on)
        ld = ld_calc if ld_posted is None else ld_posted
        if done_on and paid_on and done_on > paid_on:
            errors.append("काम सम्पन्न मिति भुक्तानी मितिभन्दा पछि हुन सक्दैन।")
        if done_on and contract.contract_date and done_on < contract.contract_date:
            errors.append("काम सम्पन्न मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if ld > ld_calc + 1:
            errors.append(f"ढिलाइ हर्जाना हिसाबअनुसार रु. {money(ld_calc)} ({np(ld_days)} दिन) — त्योभन्दा बढी कट्न मिल्दैन।")
        elif ld < ld_calc - 1 and not ld_note:
            errors.append(f"ढिलाइ हर्जाना हिसाबअनुसार रु. {money(ld_calc)} ({np(ld_days)} दिन ढिला, {bs_date(ld_last)} पछि) — "
                          "कम वा छुट गर्ने भए कारण / निर्णय लेख्नुहोस्।")
        if mbs["has"] and total_eval is not None and abs(total_eval - mbs["value"]) > 1:
            if not request.POST.get("mb_override"):
                errors.append(f"नापी किताबअनुसार कुल मूल्याङ्कन रु. {money(mbs['value'])} — अन्तिम बिल त्यही हुनुपर्छ "
                              "(फरक राख्ने भए “नापी किताबभन्दा फरक” छानी कैफियतमा कारण लेख्नुहोस्)।")
            elif not (request.POST.get("remarks") or "").strip():
                errors.append("नापी किताबभन्दा फरक रकम राख्दा कैफियतमा कारण लेख्नुहोस्।")
        if total_eval is not None:
            if total_eval < last_cum:
                errors.append(f"कुल मूल्याङ्कन अन्तिम रनिङ बिल (रु. {money(last_cum)}) भन्दा कम हुन सक्दैन।")
            from .contracts import revised_amount
            rev = revised_amount(bid, contract)
            if contract_amount and total_eval > rev + 1:
                errors.append(f"कुल मूल्याङ्कन संशोधित सम्झौता रकम रु. {money(rev)} भन्दा बढी — पहिले भेरिएसन आदेश स्वीकृत गर्नुहोस्।")
        tax_total = sum((t or ZERO for t in taxes.values()), ZERO)
        # बाँकी भुक्तानी = कुल मूल्याङ्कन − रनिङमा दिइसकेको (कुल) − कट्टी गर्न बाँकी अग्रिम − कर − ढिलाइ हर्जाना
        base = (total_eval or ZERO) - run_gross - (adv_total - adv_adjusted)
        computed = base - tax_total - (ld or ZERO)
        final_amount = posted_final if posted_final else computed
        if not errors and final_amount <= 0:
            errors.append("खुद भुक्तानी रकम ० भन्दा बढी हुनुपर्छ।")
        if not errors and (e := check_payment(project, total_eval, "अन्तिम बिल")):
            errors.append(e)
        if not errors:
            obj = fp or FinalPayment(contract=contract)
            obj.bidding_amount = contract_amount
            obj.total_advance_payment = adv_total
            obj.total_evaluation_amount = total_eval
            obj.total_running_bill_amount = run_gross
            for k, t in taxes.items():
                setattr(obj, k, t or ZERO)
            obj.completion_date, obj.ld_days, obj.ld_amount = done_on, ld_days, ld or ZERO
            obj.ld_note = ld_note
            if mbs["has"]:
                mbk.mark_billed(project, len(runs) + 1, date.today())
            obj.final_amount, obj.payment_date, obj.remarks = final_amount, paid_on, remarks
            obj.save()
            bid.status = 4
            bid.save(update_fields=["status"])
            project.status = 2
            project.save(update_fields=["status"])
            if final_amount != computed:
                messages.warning(request, f"खुद भुक्तानी हातैले राखिएको (हिसाबअनुसार रु. {money(computed)})।")
            messages.success(request, f"अन्तिम बिल सुरक्षित भयो — खुद भुक्तानी रु. {money(final_amount)}। "
                                      "भौतिक उपलब्धि भरेर अन्तिम टिप्पणी छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    g = lambda k: plain(getattr(fp, k)) if fp else "0"  # noqa: E731
    from .contracts import compute_ld
    ld_info = compute_ld(bid, contract, (fp.completion_date if fp and fp.completion_date else date.today()))
    return _render_form(request, project, {
        "title": "अन्तिम मूल्याङ्कन / बिल", "icon": "file-invoice-dollar", "errors": errors, "script": "final",
        "submit": "सुरक्षित गर्नुहोस्",
        "calc": {"run_gross": plain(run_gross), "adv_left": plain(adv_total - adv_adjusted)},
        "note": f"ठेक्का रकम रु. {money(contract_amount)} · रनिङमा भुक्तानी योग्य रु. {money(run_gross)} "
                f"({len(runs)} रनिङ) · कट्टी गर्न बाँकी अग्रिम रु. {money(adv_total - adv_adjusted)}",
        "sections": [
            {"title": "मूल्याङ्कन", "icon": "ruler-combined", "fields": [
                F("total_evaluation_amount", "कुल मूल्याङ्कन रकम (रु.)",
                  v("total_evaluation_amount", plain(fp.total_evaluation_amount) if fp else plain(mbs["value"]) if mbs["has"]
                    else plain(last_cum) if runs else ""),
                  attrs="data-calc", hint=(f"नापी किताबअनुसार रु. {money(mbs['value'])} · भौतिक प्रगति {np(mbs['progress'])}%"
                                           if mbs["has"] else "सम्पूर्ण कामको अन्तिम नापी अनुसार")),
                F("payment_date", "भुक्तानी मिति", v("payment_date", to_bs(fp.payment_date) if fp else to_bs(date.today())),
                  kind="date"),
                F("completion_date", "काम सम्पन्न मिति", v("completion_date", to_bs(fp.completion_date) if fp and fp.completion_date
                                                             else to_bs(date.today())), kind="date",
                  hint=f"हर्जाना लाग्ने अन्तिम मिति: {bs_date(ld_info[2]) or '—'}"),
            ]},
            {"title": "ढिलाइ हर्जाना", "icon": "hourglass-end", "fields": [
                F("ld_amount", "ढिलाइ हर्जाना (रु.)", v("ld_amount", plain(fp.ld_amount) if fp else plain(ld_info[1])),
                  required=False, attrs="data-calc",
                  hint=f"सम्झौता रकमको दैनिक {np(ld_info[3])}%, बढीमा रु. {money(ld_info[4])} · "
                       f"आज सम्पन्न मान्दा {np(ld_info[0])} दिन ढिला"),
                F("ld_note", "हर्जाना कम / छुट गरेको कारण", v("ld_note", fp.ld_note if fp else ""), required=False, wide=True),
            ]},
            {"title": "कर कट्टी", "icon": "receipt", "fields":
                [F(k, lbl + " (रु.)", v(k, g(k)), required=False, attrs="data-calc") for k, lbl in TAX_FIELDS]},
            {"title": "अन्तिम भुक्तानी", "icon": "circle-check", "fields": [
                F("final_amount", "खुद भुक्तानी रकम (रु.)", v("final_amount", plain(fp.final_amount) if fp else ""),
                  required=False, hint="स्वतः हिसाब हुन्छ; आवश्यक परे सच्याउन सकिन्छ"),
                F("remarks", "कैफियत", v("remarks", fp.remarks if fp and fp.remarks else ""), required=False),
            ] + ([F("mb_override", "", v("mb_override"), kind="checkbox", required=False, wide=True,
                    hint="नापी किताबभन्दा फरक रकम (कारण कैफियतमा)")] if mbs["has"] else [])},
        ],
    })
