"""दरभाउपत्र खरिद कार्यप्रवाह — सूची, चरण panel, हरेक चरणको फारम र रुजु / स्वीकृत.

फारमका सहायक (Form, मिति, रकम) बोलपत्रकै (biddings.views_workflow) प्रयोग हुन्छन्।
"""
from datetime import date
from decimal import Decimal
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
from accounts.permissions import has_perm
from biddings.views_workflow import F, Form, plain, to_bs
from projects.budget import check_payment, over_budget_warning
from projects.budget import spent as budget_spent
from projects.models import FiscalYear
from usercommittee.workflow import approver_identity, bs_date

from .models import Quation, QuationAdvance, QuationApproval, QuationFinal, Suchikrit
from .workflow import (COLUMNS, MIN_FIRMS, ZERO, D, bids, can_approve, current_quation, dump_bids, final_of, lowest,
                       money, np, pct_below, quot_workflow, row_cells, with_next, workflow_queryset)
from projects.procurement import contingency_amount, contingency_pct

LABEL = "दरभाउपत्र खरिद"


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
    return get_object_or_404(_scoped(request)[0], id=project_id)


def _guard(request, perm="quot.manage"):
    if not has_perm(request.user, perm):
        messages.error(request, "यो काम गर्ने अनुमति तपाईंलाई छैन।")
        return redirect("quot_workflow")
    return None


def with_open(url, project_id):
    from urllib.parse import parse_qsl, urlencode

    parts = urlparse(url)
    if parts.path.rstrip("/") != reverse("quot_workflow").rstrip("/"):
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "open"]
    q.append(("open", str(project_id)))
    return parts.path + "?" + urlencode(q)


def _next(request, project):
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return with_open(reverse("quot_workflow"), project.id)


def _cards(q):
    if q is None:
        return []
    cards = [{"label": "लागत अनुमान", "value": f"रु. {money(q.cost_estimate)}"}]
    firm, price = lowest(q)
    if price:
        below = pct_below(q.cost_estimate, price)
        cards.append({"label": "न्यूनतम कबोल", "value": f"रु. {money(price)}", "brand": True,
                      "sub": (f"{below}% घटी" if below >= 0 else f"{-below}% बढी") if below is not None else ""})
        cards.append({"label": "न्यूनतम दरदाता", "value": firm, "wide": True})
    return cards


def _render_form(request, project, ctx):
    q = current_quation(project)
    if ctx.get("script") == "quot_final" or ctx.get("icon") == "wallet":   # भुक्तानी फारम
        from projects.budget import budget_note
        ctx["note"] = (ctx.get("note", "") + " · " if ctx.get("note") else "") + budget_note(project)
    return render(request, "biddings/wf_form.html", {
        "module_label": LABEL, "project": project, "cards": _cards(q),
        "next": request.POST.get("next") or request.GET.get("next", ""), "back": _next(request, project),
    } | ctx)


# ---------------------------------------------------------------- सूची र panel
@login_required
def workflow_list(request):
    if not has_perm(request.user, "quot.view"):
        return redirect("unauthorized")
    qs, wards = _scoped(request)
    q = request.GET.get("q", "").strip()
    ward = request.GET.get("ward", "")
    from projects.fiscal import default_fy_param

    fy = default_fy_param(request)   # पूर्वनिर्धारित: चालु आ.व.
    stage = request.GET.get("stage", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(address__icontains=q)
                       | Q(quation__suchikrit__firm_name__icontains=q)).distinct()
    if ward.isdigit():
        qs = qs.filter(ward_id=ward)
    if fy.isdigit():
        qs = qs.filter(fiscalyear_id=fy)

    approver = can_approve(request.user)
    rows, counts = [], {"all": 0, "running": 0, "overdue": 0, "completed": 0, "to_approve": 0, "apg_alert": 0}
    for project in qs:
        steps, summary = quot_workflow(project, request.user)
        counts["all"] += 1
        counts["completed" if summary["completed"] else "running"] += 1
        counts["overdue"] += summary["overdue"]
        counts["apg_alert"] += summary["apg_alert"]
        waiting_me = approver and summary["current_key"] == "approval"
        counts["to_approve"] += waiting_me
        if (stage == "running" and summary["completed"]) or (stage == "completed" and not summary["completed"]) \
                or (stage == "overdue" and not summary["overdue"]) or (stage == "to_approve" and not waiting_me) \
                or (stage == "apg_alert" and not summary["apg_alert"]):
            continue
        if stage and stage not in ("running", "completed", "overdue", "to_approve", "apg_alert") and summary["current_key"] != stage:
            continue
        rows.append({"project": project, "cells": row_cells(steps), "summary": summary, "waiting_me": waiting_me})

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
                steps, summary = quot_workflow(project, request.user)
                row = {"project": project, "cells": row_cells(steps), "summary": summary,
                       "waiting_me": approver and summary["current_key"] == "approval"}
        if row is not None:
            page_rows.insert(0, row)
        else:
            open_id = None

    keep = request.GET.copy()
    keep.pop("page", None)
    keep.pop("open", None)
    return render(request, "quatation/workflow.html", {
        "page": page, "rows": page_rows, "open_id": open_id, "columns": COLUMNS, "counts": counts,
        "wards": Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all(),
        "fiscal_years": FiscalYear.objects.all().order_by("-name"),
        "f": {"q": q, "ward": ward, "fiscalyear": fy, "stage": stage, "per_page": per_page},
        "keep_qs": keep.urlencode(), "return_to": request.get_full_path(), "is_approver": approver,
        "firm_count": Suchikrit.objects.filter(enlisted=True, is_active=True).count(),
    })


def _return_to(request):
    current = urlparse(request.headers.get("HX-Current-URL", ""))
    if current.path:
        return current.path + ("?" + current.query if current.query else "")
    return reverse("quot_workflow")


@login_required
def workflow_detail(request, project_id):
    if not has_perm(request.user, "quot.view"):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>अनुमति छैन।</div>", status=403)
    project = _project(request, project_id)
    steps, summary = quot_workflow(project, request.user)
    from projects.fiscal import lock_steps, old_message

    fy_locked = lock_steps(project, steps)
    with_next(steps, with_open(_return_to(request), project.id), summary)
    focus = request.GET.get("step")
    return render(request, "quatation/_workflow_detail.html", {
        "project": project, "steps": steps, "summary": summary,
        "fy_locked": fy_locked, "fy_lock_msg": old_message(project) if fy_locked else "",
        "focus": int(focus) if focus and focus.isdigit() else summary["current"],
    })


# ---------------------------------------------------------------- १. लागत अनुमान र आह्वान
@login_required
def invite(request, project_id):
    if (r := _guard(request)):
        return r
    project = _project(request, project_id)
    q = current_quation(project)
    if q is not None and bids(q):
        messages.error(request, "दरभाउपत्र प्राप्त भइसकेपछि आह्वान विवरण बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    from projects.procurement import plan_gate
    if q is None and (gate := plan_gate(project)):
        messages.error(request, gate)
        return redirect("app_plan", project.id)
    errors = []
    from projects import firms as _fm
    all_firms = [x for x in Suchikrit.objects.filter(enlisted=True, is_active=True).order_by("firm_name")
                 if not _fm.blocked(x)]
    if request.method == "POST":
        f = Form(request)
        estimate = f.amount("cost_estimate", "लागत अनुमान (भ्याट सहित)")
        contingency = f.amount("contingency", "कन्टिन्जेन्सी", required=False, positive=False)
        invited = f.day("invite_date", "आह्वान मिति")
        deadline = f.day("submission_deadline", "पेश गर्ने अन्तिम मिति")
        firm_ids = [int(x) for x in request.POST.getlist("firms") if x.isdigit()]
        firms = list(Suchikrit.objects.filter(id__in=firm_ids))
        errors = f.errors
        from projects import firms as fm
        errors += [e for e in (fm.blocked(x) for x in firms) if e]
        if len(firms) < MIN_FIRMS:
            errors.append(f"कम्तीमा {np(MIN_FIRMS)} वटा सूचीकृत फर्म छान्नुहोस् (अहिले {np(len(firms))})।")
        if invited and deadline and deadline <= invited:
            errors.append("पेश गर्ने अन्तिम मिति आह्वान मितिभन्दा पछि हुनुपर्छ।")
        if not errors:
            with transaction.atomic():
                obj = q or Quation(project=project, is_invited=True)
                obj.cost_estimate, obj.contingency = estimate, float(contingency or 0)
                obj.invite_date, obj.submission_deadline = invited, deadline
                obj.save()
                obj.suchikrit.set(firms)
                if project.status == 0:
                    project.status = 1
                    project.save(update_fields=["status"])
            if project.budget and estimate > D(project.budget):
                messages.warning(request, f"लागत अनुमान विनियोजित रकम (रु. {money(project.budget)}) भन्दा बढी छ।")
            messages.success(request, f"“{project.name}” को दरभाउपत्र आह्वान सुरक्षित भयो। अब आह्वान पत्र छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    chosen = {int(x) for x in p.getlist("firms")} if p else {fm.id for fm in (q.suchikrit.all() if q else [])}
    add_url = reverse("add_suchikrit_list") + "?next=" + request.get_full_path()
    return _render_form(request, project, {
        "title": "लागत अनुमान र दरभाउपत्र आह्वान", "icon": "envelope-open-text", "errors": errors,
        "submit": "सुरक्षित गर्नुहोस्",
        "note": f"सूचीकृत फर्ममध्ये कम्तीमा {np(MIN_FIRMS)} वटा छान्नुहोस्। सूचीमा नभएको फर्म पहिले सूचीकृत गर्नुहोस्।",
        "note_link": {"url": add_url, "label": "नयाँ फर्म सूचीकृत गर्नुहोस्"},
        "sections": [
            {"title": "लागत अनुमान", "icon": "calculator", "fields": [
                F("cost_estimate", "लागत अनुमान (भ्याट सहित, रु.)", v("cost_estimate", plain(q.cost_estimate) if q else "")),
                F("contingency", "कन्टिन्जेन्सी (रु.)",
                  v("contingency", plain(q.contingency) if q and q.contingency else
                    plain(contingency_amount("quot", project.budget)) if project.budget else ""),
                  required=False, hint=f"विनियोजनको {np(contingency_pct('quot').normalize())}% (सेटिङअनुसार) सुझाव"),
            ]},
            {"title": "आह्वान", "icon": "calendar-days", "fields": [
                F("invite_date", "आह्वान मिति", v("invite_date", to_bs(q.invite_date) if q and q.invite_date else to_bs(date.today())),
                  kind="date"),
                F("submission_deadline", "दरभाउपत्र पेश गर्ने अन्तिम मिति",
                  v("submission_deadline", to_bs(q.submission_deadline) if q and q.submission_deadline else ""), kind="date"),
            ]},
            {"title": "आह्वान गरिने सूचीकृत फर्म", "icon": "building", "fields": [
                {**F("firms", f"फर्म छान्नुहोस् ({np(len(all_firms))} सूचीकृत)", kind="checks", wide=True),
                 "options": [{"value": fm.id, "label": fm.firm_name, "checked": fm.id in chosen,
                              "sub": " · ".join(x for x in (fm.firm_address, f"PAN {fm.firm_pan}" if fm.firm_pan else "",
                                                            fm.firm_contact) if x)} for fm in all_firms]},
            ]},
        ],
    })


# ---------------------------------------------------------------- २. प्राप्त दरभाउपत्र
@login_required
def quotes(request, project_id):
    if (r := _guard(request)):
        return r
    project = _project(request, project_id)
    q = current_quation(project)
    if q is None:
        messages.error(request, "पहिले दरभाउपत्र आह्वान गर्नुहोस्।")
        return redirect(_next(request, project))
    if hasattr(q, "approval"):
        messages.error(request, "स्वीकृत भइसकेपछि प्राप्त दर बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    firms = list(q.suchikrit.all())
    existing = dict(bids(q))
    errors = []
    if request.method == "POST":
        f = Form(request)
        opened = f.day("opening_date", "दरभाउपत्र खोलेको मिति")
        pairs = []
        for fm in firms:
            amt = f.amount(f"bid_{fm.id}", fm.firm_name, required=False, positive=False)
            if amt:
                pairs.append((fm.firm_name, amt))
        errors = f.errors
        if not pairs and not errors:
            errors.append("कम्तीमा एउटा फर्मको कबोल रकम भर्नुहोस्।")
        if opened and q.submission_deadline and opened < q.submission_deadline:
            errors.append("दरभाउपत्र पेश गर्ने अन्तिम मितिअघि खोल्न मिल्दैन।")
        if not errors:
            dump_bids(q, pairs)
            q.opening_date = opened
            q.save()
            if len(pairs) < MIN_FIRMS:
                messages.warning(request, f"{np(len(pairs))} वटा मात्र दरभाउपत्र प्राप्त — कारण टिप्पणीमा खुलाउनुहोस्।")
            firm, price = min(pairs, key=lambda x: x[1])
            messages.success(request, f"प्राप्त दर सुरक्षित भयो। न्यूनतम: {firm} रु. {money(price)}। अब स्वीकृतिका लागि पठाउनुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    return _render_form(request, project, {
        "title": "दरभाउपत्र प्राप्ति र तुलना", "icon": "scale-balanced", "errors": errors, "submit": "सुरक्षित गर्नुहोस्",
        "note": f"लागत अनुमान रु. {money(q.cost_estimate)} · पेश गर्ने अन्तिम मिति {bs_date(q.submission_deadline) or '—'} · "
                "दरभाउपत्र नआएको फर्मको रकम खाली छोड्नुहोस्।",
        "sections": [
            {"title": "खोलेको मिति", "icon": "calendar-days", "fields": [
                F("opening_date", "दरभाउपत्र खोलेको मिति",
                  p.get("opening_date", to_bs(q.opening_date) if q.opening_date else to_bs(date.today())), kind="date"),
            ]},
            {"title": "फर्मअनुसार कबोल रकम (भ्याट सहित, रु.)", "icon": "list-ol", "fields": [
                F(f"bid_{fm.id}", fm.firm_name, p.get(f"bid_{fm.id}", plain(existing.get(fm.firm_name, ""))),
                  required=False, hint=fm.firm_address) for fm in firms
            ]},
        ],
    })


# ---------------------------------------------------------------- ३. रुजु / स्वीकृत (modal)
@login_required
def approve(request, project_id):
    project = _project(request, project_id)
    q = current_quation(project)
    allowed = can_approve(request.user)
    approval = getattr(q, "approval", None) if q else None
    if not allowed and not (approval and has_perm(request.user, "quot.view")):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>तपाईंलाई दरभाउपत्र स्वीकृत गर्ने अधिकार छैन।</div>",
                            status=403)
    pairs = sorted(bids(q), key=lambda x: x[1]) if q else []
    problems, warnings = [], []
    if not pairs:
        problems.append("प्राप्त दरभाउपत्र भरिएको छैन।")
    elif not approval:
        from projects import firms as fm
        if (e := fm.blocked(fm.find(pairs[0][0]), pairs[0][0])):
            problems.append(e)
    if q and not approval:
        if len(pairs) < MIN_FIRMS:
            warnings.append(f"{np(len(pairs))} वटा मात्र दरभाउपत्र प्राप्त भएको छ।")
        if pairs and pairs[0][1] > D(q.cost_estimate):
            warnings.append("न्यूनतम कबोल लागत अनुमानभन्दा बढी छ।")
        if pairs and (w := over_budget_warning(project, pairs[0][1], "न्यूनतम कबोल")):
            warnings.append(w)
        if not q.prints.filter(doc_type="invite_letter").exists():
            warnings.append("आह्वान पत्र छापिएको अभिलेख छैन।")
    if request.method == "POST":
        if not allowed:
            return HttpResponse("<p class='text-sm text-rose-600'>स्वीकृत गर्ने अधिकार छैन।</p>", status=403)
        if approval is not None:
            return HttpResponse("<p class='text-sm text-rose-600'>पहिले नै स्वीकृत भइसकेको छ।</p>", status=400)
        if problems:
            return HttpResponse("<p class='text-sm text-rose-600'>" + " ".join(problems) + "</p>", status=400)
        name, post = approver_identity(request.user, "municipal")
        QuationApproval.objects.create(quation=q, approved_by=request.user, approver_name=name, approver_post=post,
                                       firm_name=pairs[0][0], amount=pairs[0][1],
                                       remarks=request.POST.get("remarks", "").strip())
        q.is_selected = True
        q.save(update_fields=["is_selected"])
        messages.success(request, f"“{project.name}”: {pairs[0][0]} को रु. {money(pairs[0][1])} को दरभाउपत्र स्वीकृत भयो। "
                                  "अब सम्झौता र कार्यादेश तयार गर्नुहोस्।")
        response = HttpResponse(status=204)
        response["HX-Redirect"] = with_open(_return_to(request), project.id)
        return response
    name, post = approver_identity(request.user, "municipal")
    est = D(q.cost_estimate) if q else ZERO
    rows = [{"firm": f, "price": p, "below": pct_below(est, p), "lowest": i == 0} for i, (f, p) in enumerate(pairs)]
    return render(request, "quatation/_approve_modal.html", {
        "project": project, "q": q, "rows": rows, "problems": problems, "warnings": warnings, "approval": approval,
        "can_approve": allowed, "name": name, "post": post,
        "invited": list(q.suchikrit.all()) if q else [],
        "dates": [("आह्वान", bs_date(q.invite_date)), ("पेश गर्ने अन्तिम", bs_date(q.submission_deadline)),
                  ("खोलेको", bs_date(q.opening_date))] if q else [],
    })


# ---------------------------------------------------------------- ४. सम्झौता
@login_required
def agreement(request, project_id):
    if (r := _guard(request)):
        return r
    project = _project(request, project_id)
    q = current_quation(project)
    if q is None or not (hasattr(q, "approval") or q.agreement_date):
        messages.error(request, "सम्झौता अघि दरभाउपत्र रुजु / स्वीकृत हुनुपर्छ।")
        return redirect(_next(request, project))
    if final_of(q) is not None:
        messages.error(request, "अन्तिम बिल भइसकेपछि सम्झौता मिति बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    errors = []
    if request.method == "POST":
        f = Form(request)
        signed = f.day("agreement_date", "सम्झौता मिति")
        ends = f.day("expire_date", "काम सम्पन्न गर्नुपर्ने मिति")
        errors = f.errors
        if signed and ends and ends <= signed:
            errors.append("काम सम्पन्न गर्नुपर्ने मिति सम्झौता मितिभन्दा पछि हुनुपर्छ।")
        appr = getattr(q, "approval", None)
        if signed and appr and signed < appr.approved_at.date():
            errors.append("सम्झौता मिति स्वीकृत मितिभन्दा अघि हुन सक्दैन।")
        if not errors:
            q.agreement_date, q.expire_date = signed, ends
            q.save(update_fields=["agreement_date", "expire_date"])
            messages.success(request, "सम्झौता विवरण सुरक्षित भयो। अब सम्झौता पत्र र कार्यादेश छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    return _render_form(request, project, {
        "title": "सम्झौता", "icon": "handshake", "errors": errors, "submit": "सुरक्षित गर्नुहोस्",
        "sections": [{"title": "सम्झौता", "icon": "file-contract", "fields": [
            F("agreement_date", "सम्झौता मिति", p.get("agreement_date", to_bs(q.agreement_date) if q.agreement_date else to_bs(date.today())),
              kind="date"),
            F("expire_date", "काम सम्पन्न गर्नुपर्ने मिति", p.get("expire_date", to_bs(q.expire_date) if q.expire_date else ""),
              kind="date"),
        ]}],
    })


# ---------------------------------------------------------------- ५. अन्तिम बिल
@login_required
def final(request, project_id):
    if not has_perm(request.user, "uc.valuation") and (r := _guard(request)):   # अन्तिम मूल्याङ्कन (इन्जिनियर) पनि
        return r
    project = _project(request, project_id)
    q = current_quation(project)
    if q is None or not q.agreement_date:
        messages.error(request, "अन्तिम बिल अघि सम्झौता चाहिन्छ।")
        return redirect(_next(request, project))
    if q.prints.filter(doc_type="final_tippani").exists():
        messages.error(request, "अन्तिम टिप्पणी छापिइसकेकाले अन्तिम बिल बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    fin = final_of(q)
    _firm, agreed = lowest(q)
    agreed = D(agreed)
    advance = sum((D(a.approved_amount) for a in q.advances.all()), ZERO)
    errors = []
    if request.method == "POST":
        f = Form(request)
        on = f.day("application_date", "भुक्तानी / बिल मिति")
        valuation = f.amount("totalValuation", "कुल मूल्याङ्कन रकम")
        retention = f.amount("retension", "धरौटी (रिटेन्सन)", required=False, positive=False)
        tax = f.amount("taxdeduction", "कर कट्टी", required=False, positive=False)
        posted = f.amount("finalpayment", "खुद भुक्तानी", required=False, positive=False)
        errors = f.errors
        if valuation is not None and agreed and valuation > agreed * Decimal("1.15"):
            errors.append("कुल मूल्याङ्कन सम्झौता रकमको ११५% भन्दा बढी हुन सक्दैन।")
        computed = (valuation or ZERO) - (retention or ZERO) - (tax or ZERO) - advance
        net = posted if posted else computed
        if not errors and net <= 0:
            errors.append("खुद भुक्तानी रकम ० भन्दा बढी हुनुपर्छ।")
        if not errors and (e := check_payment(project, valuation, "अन्तिम बिल")):
            errors.append(e)
        if on and q.agreement_date and on < q.agreement_date:
            errors.append("बिल मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if not errors:
            obj = fin or QuationFinal(quation=q)
            obj.application_date, obj.totalValuation = on, float(valuation)
            obj.retension, obj.taxdeduction, obj.finalpayment = float(retention or 0), float(tax or 0), float(net)
            obj.advance_deducted = float(advance)
            obj.save()
            project.status = 2
            project.save(update_fields=["status"])
            if agreed and valuation > agreed:
                messages.warning(request, "कुल मूल्याङ्कन सम्झौता रकमभन्दा बढी छ।")
            if net != computed:
                messages.warning(request, f"खुद भुक्तानी हातैले राखिएको (हिसाबअनुसार रु. {money(computed)})।")
            messages.success(request, f"अन्तिम बिल सुरक्षित भयो — खुद भुक्तानी रु. {money(net)}। "
                                      "भौतिक उपलब्धि भरेर अन्तिम टिप्पणी छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    g = lambda k, d="": p.get(k, plain(getattr(fin, k)) if fin and getattr(fin, k) is not None else d)  # noqa: E731
    return _render_form(request, project, {
        "title": "अन्तिम मूल्याङ्कन / बिल", "icon": "file-invoice-dollar", "errors": errors, "submit": "सुरक्षित गर्नुहोस्",
        "script": "quot_final", "calc": {"advance": plain(advance) or "0"},
        "note": f"सम्झौता रकम (न्यूनतम कबोल) रु. {money(agreed)} · धरौटी सामान्यतया ५%"
                + (f" · अग्रिम भुक्तानी रु. {money(advance)} कट्टी हुन्छ" if advance else ""),
        "sections": [
            {"title": "मूल्याङ्कन", "icon": "ruler-combined", "fields": [
                F("application_date", "बिल मिति", p.get("application_date", to_bs(fin.application_date) if fin and fin.application_date
                                                       else to_bs(date.today())), kind="date"),
                F("totalValuation", "कुल मूल्याङ्कन रकम (रु.)", g("totalValuation"), attrs="data-calc"),
            ]},
            {"title": "कट्टी र खुद भुक्तानी", "icon": "receipt", "fields": [
                F("retension", "धरौटी / रिटेन्सन (रु.)", g("retension"), required=False, hint="मूल्याङ्कनको ५% (स्वतः)"),
                F("taxdeduction", "कर कट्टी (रु.)", g("taxdeduction", "0"), required=False),
                F("advance_deducted", "अग्रिम भुक्तानी कट्टी (रु.)", plain(advance) or "0", required=False, readonly=True,
                  hint="दिइसकेको सबै अग्रिम (स्वतः)"),
                F("finalpayment", "खुद भुक्तानी रकम (रु.)", g("finalpayment"), required=False,
                  hint="स्वतः हिसाब हुन्छ; आवश्यक परे सच्याउन सकिन्छ"),
            ]},
        ],
    })


# ---------------------------------------------------------------- ऐच्छिक: अग्रिम भुक्तानी (+ बैंक जमानत)
@login_required
def advance(request, project_id):
    if (r := _guard(request)):
        return r
    project = _project(request, project_id)
    q = current_quation(project)
    if q is None or not q.agreement_date or final_of(q) is not None:
        messages.error(request, "अग्रिम भुक्तानी सम्झौतापछि र अन्तिम बिलअघि मात्र।")
        return redirect(_next(request, project))
    _firm, agreed = lowest(q)
    agreed = D(agreed)
    paid = sum((D(a.approved_amount) for a in q.advances.all()), ZERO)
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
        if amount is not None and paid + amount > agreed:
            errors.append("कुल अग्रिम भुक्तानी सम्झौता रकमभन्दा बढी हुन सक्दैन।")
        if amount is not None and (e := check_payment(project, budget_spent(project) + amount, "यो अग्रिम")):
            errors.append(e)
        if amount is not None and g_amount is not None and g_amount < amount:
            errors.append("अग्रिम भुक्तानी जमानत रकम अग्रिम रकमभन्दा कम हुन सक्दैन।")
        if issue and expiry and expiry <= issue:
            errors.append("जमानतको म्याद जारी मितिभन्दा पछि हुनुपर्छ।")
        if approved and approved < q.agreement_date:
            errors.append("अग्रिम स्वीकृत मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if not errors:
            QuationAdvance.objects.create(quation=q, approved_amount=amount, approval_date=approved, remarks=remarks,
                                          bank_name=bank, guarantee_number=number, guaranteed_amount=g_amount,
                                          issue_date=issue, expiry_date=expiry, document=request.FILES.get("document"))
            if agreed and paid + amount > agreed * Decimal("0.2"):
                messages.warning(request, "कुल अग्रिम सम्झौता रकमको २०% भन्दा बढी भयो — सम्झौताको शर्त जाँच्नुहोस्।")
            if q.expire_date and expiry < q.expire_date:
                messages.warning(request, "जमानतको म्याद काम सम्पन्न गर्नुपर्ने मितिअघि सकिन्छ — म्याद थप गराउनुहोस्।")
            messages.success(request, f"अग्रिम भुक्तानी रु. {money(amount)} दर्ता भयो। टिप्पणी कार्यप्रवाहबाट छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    return _render_form(request, project, {
        "title": "अग्रिम भुक्तानी (पेश्की)", "icon": "wallet", "errors": errors, "upload": True,
        "submit": "सुरक्षित गर्नुहोस्",
        "note": f"सम्झौता रकम रु. {money(agreed)} · दिइसकेको अग्रिम रु. {money(paid)} · "
                f"सामान्य सीमा २०% = रु. {money(agreed * Decimal('0.2'))} · अन्तिम बिलमा कट्टी हुन्छ",
        "sections": [
            {"title": "अग्रिम भुक्तानी", "icon": "money-bill-wave", "fields": [
                F("approved_amount", "अग्रिम रकम (रु.)", v("approved_amount")),
                F("approval_date", "स्वीकृत मिति", v("approval_date", to_bs(date.today())), kind="date"),
                F("remarks", "कैफियत", v("remarks"), required=False),
            ]},
            {"title": "अग्रिम भुक्तानी जमानत (बैंक ग्यारेन्टी)", "icon": "building-columns", "fields": [
                F("bank_name", "बैंक", v("bank_name")),
                F("guarantee_number", "जमानत नम्बर", v("guarantee_number")),
                F("guaranteed_amount", "जमानत रकम (रु.)", v("guaranteed_amount"), hint="अग्रिम रकम बराबर वा बढी"),
                F("issue_date", "जारी मिति", v("issue_date"), kind="date"),
                F("expiry_date", "म्याद (मिति)", v("expiry_date", to_bs(q.expire_date) if q.expire_date else ""), kind="date",
                  hint="कम्तीमा काम सम्पन्न गर्नुपर्ने मितिसम्म"),
                F("document", "जमानतको स्क्यान (ऐच्छिक)", kind="file", required=False, hint="PDF वा फोटो"),
            ]},
        ],
    })


@login_required
def advance_guarantees(request):
    """दरभाउपत्रका अग्रिम भुक्तानी जमानत — म्याद अनुसार."""
    if not has_perm(request.user, "quot.view"):
        return redirect("unauthorized")
    wards = _user_wards(request.user)
    rows = QuationAdvance.objects.select_related("quation__project__ward").order_by("expiry_date")
    if wards is not None:
        rows = rows.filter(quation__project__ward_id__in=wards)
    items = []
    for a in rows:
        fin = final_of(a.quation)
        firm, _p = lowest(a.quation)
        items.append({"a": a, "firm": firm, "closed": fin is not None, "issue_bs": bs_date(a.issue_date),
                      "expiry_bs": bs_date(a.expiry_date), "approval_bs": bs_date(a.approval_date)})
    return render(request, "quatation/advance_guarantees.html", {"items": items})
