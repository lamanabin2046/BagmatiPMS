"""संस्था / समिति मार्फत खरिद — सूची, चरण panel, हरेक चरणको फारम, रुजु / स्वीकृत र छाप्ने कागजात.

चरणको नियम र स्थिति: projects/sanstha.py. फारम ढाँचा बोलपत्र / दरभाउपत्रकै (biddings/wf_form.html).
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
from django.utils import timezone

from accounts.models import Ward
from accounts.permissions import has_perm, user_perms
from biddings.views_workflow import F, Form, plain, to_bs
from usercommittee.workflow import approver_identity, bs_date

from . import firms as fm
from . import minor as mn
from . import sanstha as sn
from .models import FiscalYear, MinorPayment, MinorPrint, MinorProcurement, MinorQuote

VIEW = {"minor.view", "minor.manage", "minor.approve", "minor.print"}
EXTRA_ROWS = 3


def _user_wards(user):
    from usercommittee.views_workflow import _user_wards as uw

    return uw(user)


def _scoped(request):
    qs = sn.workflow_queryset()
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    return qs, wards


def _project(request, project_id):
    return get_object_or_404(_scoped(request)[0], id=project_id)


def _guard(request, perm="minor.manage"):
    if not has_perm(request.user, perm):
        messages.error(request, "यो काम गर्ने अनुमति तपाईंलाई छैन।")
        return redirect("sanstha_workflow")
    return None


def with_open(url, project_id):
    from urllib.parse import parse_qsl, urlencode

    parts = urlparse(url)
    if parts.path.rstrip("/") != reverse("sanstha_workflow").rstrip("/"):
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "open"]
    q.append(("open", str(project_id)))
    return parts.path + "?" + urlencode(q)


def _next(request, project):
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return with_open(reverse("sanstha_workflow"), project.id)


def _m(project):
    m = mn.minor_of(project)
    return m if m is not None and m.method == "sanstha" else None


def _cards(project, m):
    cards = [{"label": "विनियोजित रकम", "value": f"रु. {sn.money(project.budget)}"}]
    if m is None:
        return cards
    cards.append({"label": "लागत अनुमान", "value": f"रु. {sn.money(m.estimate_amount)}"})
    sel = m.selected or sn.recommended(m)
    if sel is not None:
        below = sn.pct_below(m.estimate_amount, sel.amount)
        cards.append({"label": "स्वीकृत" if m.selected else "सिफारिस प्रस्ताव", "value": f"रु. {sn.money(sel.amount)}",
                      "brand": True, "sub": (f"{below}% घटी" if below >= 0 else f"{-below}% बढी") if below is not None else ""})
        cards.append({"label": "संस्था", "value": sel.name, "sub": sel.address})
    return cards


def _render_form(request, project, ctx):
    if ctx.get("icon") == "wallet":
        from .budget import budget_note
        ctx["note"] = (ctx.get("note", "") + " · " if ctx.get("note") else "") + budget_note(project)
    return render(request, "biddings/wf_form.html", {
        "module_label": sn.LABEL, "project": project, "cards": _cards(project, _m(project)),
        "next": request.POST.get("next") or request.GET.get("next", ""), "back": _next(request, project),
    } | ctx)


def _money(raw):
    from biddings.views_workflow import to_dec

    v = to_dec(raw)
    return None if v in (None, "bad") else v


def _return_to(request):
    current = urlparse(request.headers.get("HX-Current-URL", ""))
    if current.path:
        return current.path + ("?" + current.query if current.query else "")
    return reverse("sanstha_workflow")


# ---------------------------------------------------------------- सूची र panel
@login_required
def workflow_list(request):
    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    qs, wards = _scoped(request)
    q = request.GET.get("q", "").strip()
    from .fiscal import default_fy_param

    ward, fy, stage = request.GET.get("ward", ""), default_fy_param(request), request.GET.get("stage", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(address__icontains=q) | Q(minor__quotes__name__icontains=q)).distinct()
    if ward.isdigit():
        qs = qs.filter(ward_id=ward)
    if fy.isdigit():
        qs = qs.filter(fiscalyear_id=fy)
    approver = "minor.approve" in P
    rows, counts = [], {"all": 0, "running": 0, "overdue": 0, "completed": 0, "to_approve": 0}
    for project in qs:
        steps, s = sn.workflow(project, request.user)
        waiting = approver and s["current_key"] == "approval"
        counts["all"] += 1
        counts["completed" if s["completed"] else "running"] += 1
        counts["overdue"] += s["overdue"]
        counts["to_approve"] += waiting
        if (stage == "running" and s["completed"]) or (stage == "completed" and not s["completed"]) \
                or (stage == "overdue" and not s["overdue"]) or (stage == "to_approve" and not waiting):
            continue
        if stage and stage not in ("running", "completed", "overdue", "to_approve") and s["current_key"] != stage:
            continue
        rows.append({"project": project, "cells": sn.row_cells(steps), "summary": s, "waiting_me": waiting})
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
                steps, s = sn.workflow(project, request.user)
                row = {"project": project, "cells": sn.row_cells(steps), "summary": s,
                       "waiting_me": approver and s["current_key"] == "approval"}
        if row is not None:
            page_rows.insert(0, row)
        else:
            open_id = None
    keep = request.GET.copy()
    keep.pop("page", None)
    keep.pop("open", None)
    from quatation.models import Suchikrit
    return render(request, "projects/sanstha_workflow.html", {
        "page": page, "rows": page_rows, "open_id": open_id, "columns": sn.COLUMNS, "counts": counts,
        "wards": Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all(),
        "fiscal_years": FiscalYear.objects.all().order_by("-name"),
        "f": {"q": q, "ward": ward, "fiscalyear": fy, "stage": stage, "per_page": per_page},
        "keep_qs": keep.urlencode(), "return_to": request.get_full_path(), "is_approver": approver,
        "org_count": Suchikrit.objects.filter(kind="organization", is_active=True).count(),
    })


@login_required
def workflow_detail(request, project_id):
    if not user_perms(request.user) & VIEW:
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>अनुमति छैन।</div>", status=403)
    project = _project(request, project_id)
    steps, summary = sn.workflow(project, request.user)
    from .fiscal import lock_steps, old_message

    fy_locked = lock_steps(project, steps)
    sn.with_next(steps, with_open(_return_to(request), project.id), summary)
    focus = request.GET.get("step")
    return render(request, "projects/_sanstha_detail.html", {
        "project": project, "steps": steps, "summary": summary,
        "fy_locked": fy_locked, "fy_lock_msg": old_message(project) if fy_locked else "",
        "focus": int(focus) if focus and focus.isdigit() else summary["current"],
    })


# ---------------------------------------------------------------- १. लागत अनुमान र आह्वान
def _orgs():
    from quatation.models import Suchikrit

    return [x for x in Suchikrit.objects.filter(kind="organization", is_active=True).order_by("firm_name")
            if not fm.blocked(x)]


@login_required
def invite(request, project_id):
    if (r := _guard(request)):
        return r
    from .procurement import limits, plan_gate, rs

    project = _project(request, project_id)
    m = _m(project)
    if m is not None and m.quotes.exists():
        messages.error(request, "प्रस्ताव प्राप्त भइसकेपछि आह्वान विवरण बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    if m is None and (gate := plan_gate(project)):
        messages.error(request, gate)
        return redirect("app_plan", project.id)
    L = limits()
    plan = getattr(project, "procurement_plan", None)
    orgs = _orgs()
    errors = []
    if request.method == "POST":
        f = Form(request)
        estimate = f.amount("estimate_amount", "लागत अनुमान")
        est_day = f.day("estimate_date", "लागत अनुमान स्वीकृत मिति")
        kind = request.POST.get("notice_kind", "")
        notice = f.day("notice_date", "आह्वान / सूचना मिति")
        deadline = f.day("submission_deadline", "प्रस्ताव पेश गर्ने अन्तिम मिति")
        ref = f.text("notice_ref", "पत्र / सूचना संख्या", required=False)
        scope = f.text("scope", "कार्यक्षेत्र / कार्यविवरण")
        pass_mark = f.amount("pass_mark", "न्यूनतम प्राविधिक अङ्क", required=False, positive=False)
        ids = [int(x) for x in request.POST.getlist("orgs") if x.isdigit()]
        from quatation.models import Suchikrit
        chosen = list(Suchikrit.objects.filter(id__in=ids))
        errors = f.errors
        if kind not in dict(MinorProcurement.NOTICE_KINDS):
            errors.append("आह्वानको तरिका छान्नुहोस्।")
        if estimate is not None:
            errors += mn.check_estimate(project, plan, estimate, L)
        if estimate is not None and estimate > sn.D(L.sanstha_notice_limit) and kind == "letter":
            errors.append(f"लागत अनुमान {rs(L.sanstha_notice_limit)} भन्दा बढी भएकाले सार्वजनिक सूचना / आशयपत्र (EOI) अनिवार्य छ।")
        if kind == "letter" and len(chosen) < sn.MIN_ORGS:
            errors.append(f"पत्रबाट आह्वान गर्दा कम्तीमा {sn.np(sn.MIN_ORGS)} वटा सूचीकृत संस्था छान्नुहोस् "
                          f"(अहिले {sn.np(len(chosen))})।")
        if kind == "both" and not chosen:
            errors.append("पत्र पठाउने संस्था छान्नुहोस् (नभए “सार्वजनिक सूचना” मात्र छान्नुहोस्)।")
        errors += [e for e in (fm.blocked(x) for x in chosen) if e]
        if est_day and notice and notice < est_day:
            errors.append("आह्वान मिति लागत अनुमान मितिभन्दा अघि हुन सक्दैन।")
        if notice and deadline:
            if deadline <= notice:
                errors.append("प्रस्ताव पेश गर्ने अन्तिम मिति आह्वान मितिभन्दा पछि हुनुपर्छ।")
            elif kind in ("public", "both") and (deadline - notice).days < sn.NOTICE_DAYS:
                errors.append(f"सार्वजनिक सूचना कम्तीमा {sn.np(sn.NOTICE_DAYS)} दिनको हुनुपर्छ "
                              f"(अहिले {sn.np((deadline - notice).days)} दिन)।")
        if pass_mark is not None and pass_mark and not (0 < pass_mark <= 100):
            errors.append("न्यूनतम प्राविधिक अङ्क १ देखि १०० सम्म हुनुपर्छ।")
        if not errors:
            with transaction.atomic():
                obj = m or MinorProcurement(project=project, method="sanstha", created_by=request.user)
                obj.estimate_amount, obj.estimate_date = estimate, est_day
                obj.notice_kind, obj.notice_date, obj.submission_deadline, obj.notice_ref = kind, notice, deadline, ref
                obj.scope, obj.pass_mark = scope, (pass_mark or None)
                if request.FILES.get("estimate_doc"):
                    obj.estimate_doc = request.FILES["estimate_doc"]
                obj.save()
                obj.invited.set(chosen if kind != "public" else [])
                if project.status == 0:
                    project.status = 1
                    project.save(update_fields=["status"])
            messages.success(request, f"“{project.name}” को प्रस्ताव आह्वान सुरक्षित भयो। अब आह्वान टिप्पणी र "
                                      f"{'सूचना' if kind == 'public' else 'पत्र'} छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    chosen_ids = {int(x) for x in p.getlist("orgs")} if p else {o.id for o in (m.invited.all() if m else [])}
    default_est = m.estimate_amount if m else (plan.estimated_cost if plan and plan.estimated_cost else project.budget)
    return _render_form(request, project, {
        "title": "लागत अनुमान र प्रस्ताव आह्वान", "icon": "envelope-open-text", "errors": errors, "upload": True,
        "submit": "सुरक्षित गर्नुहोस्",
        "note": f"सार्वजनिक सूचना कम्तीमा {sn.np(sn.NOTICE_DAYS)} दिन · पत्रबाट मात्र भए कम्तीमा {sn.np(sn.MIN_ORGS)} संस्था · "
                f"रु. {sn.money(L.sanstha_notice_limit)} भन्दा बढीमा सार्वजनिक सूचना / आशयपत्र अनिवार्य",
        "note_link": {"url": reverse("firm_list") + "?kind=organization", "label": "नयाँ संस्था दर्ता गर्नुहोस्"},
        "sections": [
            {"title": "लागत अनुमान", "icon": "calculator", "fields": [
                F("estimate_amount", "लागत अनुमान (रु.)", v("estimate_amount", plain(default_est))),
                F("estimate_date", "लागत अनुमान स्वीकृत मिति", v("estimate_date", to_bs(m.estimate_date) if m else to_bs(date.today())),
                  kind="date"),
                F("estimate_doc", "लागत अनुमान (स्क्यान)", kind="file", required=False),
                F("scope", "कार्यक्षेत्र / कार्यविवरण (ToR) — के काम, कति लाभग्राही, कति अवधि", v("scope", m.scope if m else ""),
                  kind="textarea", wide=True),
            ]},
            {"title": "आह्वान", "icon": "bullhorn", "fields": [
                F("notice_kind", "आह्वानको तरिका", v("notice_kind", (m.notice_kind if m and m.notice_kind else
                                                                 ("public" if sn.D(default_est) > sn.D(L.sanstha_notice_limit) else "letter"))),
                  kind="select", options=list(MinorProcurement.NOTICE_KINDS)),
                F("notice_date", "आह्वान / सूचना मिति", v("notice_date", to_bs(m.notice_date) if m and m.notice_date else to_bs(date.today())),
                  kind="date"),
                F("submission_deadline", "प्रस्ताव पेश गर्ने अन्तिम मिति",
                  v("submission_deadline", to_bs(m.submission_deadline) if m and m.submission_deadline else ""), kind="date"),
                F("notice_ref", "पत्र / सूचना संख्या", v("notice_ref", m.notice_ref if m else ""), required=False),
                F("pass_mark", "प्राविधिक मूल्याङ्कनको न्यूनतम अङ्क (ऐच्छिक)",
                  v("pass_mark", plain(m.pass_mark) if m and m.pass_mark else ""), required=False,
                  hint="तोकिए यति अङ्क नपुगेका संस्था छनौट हुँदैनन् (जस्तै ६०)"),
            ]},
            {"title": "पत्र पठाइने सूचीकृत संस्था", "icon": "building", "fields": [
                {**F("orgs", f"संस्था छान्नुहोस् ({sn.np(len(orgs))} दर्ता) — सार्वजनिक सूचना मात्र भए खाली छोड्नुहोस्",
                     kind="checks", wide=True, required=False),
                 "options": [{"value": o.id, "label": o.firm_name, "checked": o.id in chosen_ids,
                              "sub": " · ".join(x for x in (o.firm_address, f"दर्ता / PAN {o.firm_pan}" if o.firm_pan else "",
                                                            o.firm_contact) if x)} for o in orgs]},
            ]},
        ],
    })


# ---------------------------------------------------------------- २. प्रस्ताव प्राप्ति र मूल्याङ्कन
@login_required
def proposals(request, project_id):
    if (r := _guard(request)):
        return r
    from biddings.views_workflow import to_ad

    project = _project(request, project_id)
    m = _m(project)
    if m is None or not m.notice_date:
        messages.error(request, "पहिले प्रस्ताव आह्वान गर्नुहोस्।")
        return redirect(_next(request, project))
    if m.approved_at:
        messages.error(request, "स्वीकृत भइसकेपछि प्रस्ताव बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    existing = list(m.quotes.all())
    by_firm = {q.firm_id: q for q in existing if q.firm_id}
    rows = []
    for o in m.invited.all():
        q = by_firm.pop(o.id, None)
        rows.append({"key": f"o{o.id}", "fixed": True, "name": o.firm_name, "pan": o.firm_pan, "address": o.firm_address, "q": q})
    used = {r["q"].id for r in rows if r["q"]}
    for q in existing:
        if q.id not in used:
            rows.append({"key": f"q{q.id}", "fixed": False, "name": q.name, "pan": q.pan, "address": q.address, "q": q})
    for i in range(EXTRA_ROWS):
        rows.append({"key": f"n{i}", "fixed": False, "name": "", "pan": "", "address": "", "q": None})
    errors = []
    if request.method == "POST":
        P_ = request.POST
        opened = to_ad(P_.get("opening_date"))
        if opened is None:
            errors.append("प्रस्ताव खोलेको मिति भर्नुहोस् (वि.सं. YYYY-MM-DD)।")
        elif m.submission_deadline and opened < m.submission_deadline:
            errors.append("प्रस्ताव पेश गर्ने अन्तिम मितिअघि खोल्न मिल्दैन।")
        elif opened < m.notice_date:
            errors.append("खोलेको मिति आह्वान मितिभन्दा अघि हुन सक्दैन।")
        items, seen = [], set()
        for r in rows:
            k = r["key"]
            amount = _money(P_.get(f"amount_{k}"))
            name = r["name"] if r["fixed"] else (P_.get(f"name_{k}") or "").strip()
            if amount is None and not (P_.get(f"amount_{k}") or "").strip():
                if name and not r["fixed"] and r["q"] is None:
                    errors.append(f"“{name}” को प्रस्तावित रकम भर्नुहोस्।")
                continue
            if not name:
                errors.append("रकम भरेको पङ्क्तिमा संस्थाको नाम लेख्नुहोस्।")
                continue
            if amount is None or amount <= 0:
                errors.append(f"“{name}” को रकम ० भन्दा बढी अङ्कमा लेख्नुहोस्।")
                continue
            pan = (P_.get(f"pan_{k}") if not r["fixed"] else r["pan"]) or ""
            pan = pan.strip()
            if pan and not r["fixed"] and not (pan.isdigit() and len(pan) == 9):
                errors.append(f"“{name}”: PAN ९ अङ्कको हुनुपर्छ।")
            if name in seen:
                errors.append(f"“{name}” दुई पटक लेखिएको छ।")
            seen.add(name)
            score_raw = (P_.get(f"score_{k}") or "").strip()
            score = _money(score_raw) if score_raw else None
            if score_raw and (score is None or score < 0 or score > 100):
                errors.append(f"“{name}”: प्राविधिक अङ्क ० देखि १०० सम्म।")
            qualified = bool(P_.get(f"qualified_{k}"))
            if m.pass_mark is not None and qualified and score is None:
                errors.append(f"“{name}”: न्यूनतम अङ्क तोकिएकाले प्राविधिक अङ्क भर्नुहोस्।")
            if (e := fm.blocked(fm.find(name, pan), name, pan)):
                errors.append(e)
            items.append({"r": r, "name": name, "pan": pan, "amount": amount, "score": score, "qualified": qualified,
                          "address": r["address"] if r["fixed"] else (P_.get(f"address_{k}") or "").strip(),
                          "received": to_ad(P_.get(f"received_{k}")), "remarks": (P_.get(f"remarks_{k}") or "").strip()})
        if not items and not errors:
            errors.append("कम्तीमा एउटा प्रस्ताव भर्नुहोस्।")
        for it in items:
            if it["received"] and m.submission_deadline and it["received"] > m.submission_deadline:
                errors.append(f"“{it['name']}” को प्रस्ताव पेश गर्ने अन्तिम मितिपछि प्राप्त — म्यादपछिको प्रस्ताव खोलिँदैन।")
        if not errors:
            with transaction.atomic():
                m.quotes.all().delete()
                for it in items:
                    firm = fm.find_or_create(it["name"], it["pan"], it["address"], kind="organization")
                    MinorQuote.objects.create(minor=m, firm=firm, name=it["name"], pan=it["pan"], address=it["address"],
                                              amount=it["amount"], tech_score=it["score"], qualified=it["qualified"],
                                              received_on=it["received"], remarks=it["remarks"])
                m.opening_date = opened
                m.save(update_fields=["opening_date"])
            rec = sn.recommended(m)
            if len(items) < sn.MIN_ORGS:
                messages.warning(request, f"{sn.np(len(items))} वटा मात्र प्रस्ताव प्राप्त — कारण स्वीकृति टिप्पणीमा खुलाउनुहोस्।")
            if rec is None:
                messages.warning(request, "कुनै प्रस्ताव योग्य भएन — पुनः आह्वान गर्नुपर्ने हुन सक्छ।")
            else:
                messages.success(request, f"प्रस्ताव सुरक्षित भयो। सिफारिस: {rec.name} रु. {sn.money(rec.amount)}। अब स्वीकृतिका लागि पठाउनुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else None
    for r in rows:
        k, q = r["key"], r["q"]
        g = (lambda name, d, k=k: p.get(f"{name}_{k}", "") if p is not None else d)
        r["v"] = {"name": g("name", r["name"]), "pan": g("pan", r["pan"]), "address": g("address", r["address"]),
                  "amount": g("amount", plain(q.amount) if q else ""), "score": g("score", plain(q.tech_score) if q and q.tech_score is not None else ""),
                  "qualified": (bool(p.get(f"qualified_{k}")) if p is not None else (q.qualified if q else True)),
                  "received": g("received", to_bs(q.received_on) if q and q.received_on else ""),
                  "remarks": g("remarks", q.remarks if q else "")}
    return render(request, "projects/sanstha_proposals.html", {
        "module_label": sn.LABEL, "project": project, "m": m, "rows": rows, "errors": errors,
        "cards": _cards(project, m), "back": _next(request, project),
        "next": request.POST.get("next") or request.GET.get("next", ""),
        "opening_date": (p.get("opening_date") if p is not None else
                         to_bs(m.opening_date) if m.opening_date else to_bs(max(date.today(), m.submission_deadline or date.today()))),
        "deadline_bs": bs_date(m.submission_deadline), "firm_options": fm.options(["organization"]),
    })


# ---------------------------------------------------------------- ३. रुजु / स्वीकृत (modal)
@login_required
def approve(request, project_id):
    from .budget import over_budget_warning

    project = _project(request, project_id)
    m = _m(project)
    P = user_perms(request.user)
    allowed = "minor.approve" in P
    if not allowed and not (m and m.approved_at and P & VIEW):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>तपाईंलाई स्वीकृत गर्ने अधिकार छैन।</div>", status=403)
    ranked = sn.ranked(m)
    rec = sn.recommended(m)
    problems, warnings = [], []
    if m is None or not ranked:
        problems.append("प्राप्त प्रस्ताव भरिएको छैन।")
    elif not m.approved_at:
        if rec is None:
            problems.append("कुनै प्रस्ताव योग्य छैन — पुनः आह्वान गर्नुहोस्।")
        if len(ranked) < sn.MIN_ORGS:
            warnings.append(f"{sn.np(len(ranked))} वटा मात्र प्रस्ताव प्राप्त भएको छ।")
        if rec and sn.D(rec.amount) > sn.D(m.estimate_amount):
            warnings.append("सिफारिस प्रस्ताव लागत अनुमानभन्दा बढी छ — स्वीकृत गर्न मिल्दैन।")
        if rec and (w := over_budget_warning(project, rec.amount, "सिफारिस प्रस्ताव")):
            warnings.append(w)
        if not m.prints.filter(doc_type="invite_letter").exists():
            warnings.append("आह्वान पत्र / सूचना छापिएको अभिलेख छैन।")
    if request.method == "POST":
        def fail(msg, code=400):
            return HttpResponse(f"<p class='text-sm text-rose-600'>{msg}</p>", status=code)
        if not allowed:
            return fail("स्वीकृत गर्ने अधिकार छैन।", 403)
        if m is None or m.approved_at:
            return fail("पहिले नै स्वीकृत भइसकेको छ।")
        if problems:
            return fail(" ".join(problems))
        quote = m.quotes.filter(id=request.POST.get("quote") or 0).first()
        reason = (request.POST.get("reason") or "").strip()
        if quote is None:
            return fail("छनौट हुने संस्था छान्नुहोस्।")
        if not sn.eligible(m, quote):
            return fail(f"“{quote.name}” योग्य छैन वा न्यूनतम प्राविधिक अङ्क पुगेको छैन।")
        if sn.D(quote.amount) > sn.D(m.estimate_amount) + mn.TOL:
            return fail("छानिएको रकम लागत अनुमानभन्दा बढी छ — लागत अनुमानभित्रको मात्र स्वीकृत गर्न मिल्छ।")
        if quote.id != rec.id and not reason:
            return fail("सिफारिस (न्यूनतम योग्य) बाहेक अर्को छान्दा कारण लेख्नुहोस्।")
        if (e := fm.blocked(quote.firm, quote.name, quote.pan)):
            return fail(e)
        name, post = approver_identity(request.user, "municipal")
        m.selected, m.approved_by, m.approved_at = quote, request.user, timezone.now()
        m.approver_name = f"{name} ({post})"
        m.approval_remarks = reason or (request.POST.get("remarks") or "").strip()
        m.save()
        messages.success(request, f"“{project.name}”: {quote.name} को रु. {sn.money(quote.amount)} को प्रस्ताव स्वीकृत भयो। "
                                  "अब स्वीकृति टिप्पणी छापी सम्झौता गर्नुहोस्।")
        response = HttpResponse(status=204)
        response["HX-Redirect"] = with_open(_return_to(request), project.id)
        return response
    name, post = approver_identity(request.user, "municipal")
    est = sn.D(m.estimate_amount) if m else sn.ZERO
    return render(request, "projects/_sanstha_approve.html", {
        "project": project, "m": m, "problems": problems, "warnings": warnings, "can_approve": allowed,
        "name": name, "post": post, "rec": rec, "invited": list(m.invited.all()) if m else [],
        "rows": [{"q": q, "ok": ok, "below": sn.pct_below(est, q.amount)} for q, ok in ranked],
        "dates": [("आह्वान", bs_date(m.notice_date)), ("पेश गर्ने अन्तिम", bs_date(m.submission_deadline)),
                  ("खोलेको", bs_date(m.opening_date))] if m else [],
    })


# ---------------------------------------------------------------- ४. सम्झौता
@login_required
def agreement(request, project_id):
    if (r := _guard(request)):
        return r
    project = _project(request, project_id)
    m = _m(project)
    if m is None or not m.approved_at:
        messages.error(request, "सम्झौता अघि प्रस्ताव रुजु / स्वीकृत हुनुपर्छ।")
        return redirect(_next(request, project))
    if m.payments.exists():
        messages.error(request, "भुक्तानी भइसकेपछि सम्झौता बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    limit = sn.D(m.selected.amount) if m.selected else sn.D(m.estimate_amount)
    errors = []
    if request.method == "POST":
        f = Form(request)
        signed = f.day("order_date", "सम्झौता मिति")
        due = f.day("due_date", "काम सम्पन्न गर्नुपर्ने मिति")
        amount = f.amount("order_amount", "सम्झौता रकम")
        no = f.text("order_no", "सम्झौता / पत्र नं.", required=False)
        share = f.amount("cost_share", "संस्थाको लागत सहभागिता", required=False, positive=False)
        errors = f.errors
        if signed and signed < m.approved_at.date():
            errors.append("सम्झौता मिति स्वीकृत मितिभन्दा अघि हुन सक्दैन।")
        if signed and due and due <= signed:
            errors.append("काम सम्पन्न गर्नुपर्ने मिति सम्झौता मितिभन्दा पछि हुनुपर्छ।")
        if amount is not None and amount > limit + mn.TOL:
            errors.append(f"सम्झौता रकम स्वीकृत प्रस्ताव रु. {sn.money(limit)} भन्दा बढी हुन सक्दैन।")
        if not errors:
            m.order_date, m.due_date, m.order_amount, m.order_no = signed, due, amount, no
            m.cost_share = share or None
            m.save(update_fields=["order_date", "due_date", "order_amount", "order_no", "cost_share"])
            messages.success(request, "सम्झौता विवरण सुरक्षित भयो। अब सम्झौता पत्र र कार्यादेश छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    return _render_form(request, project, {
        "title": "सम्झौता र कार्यादेश", "icon": "handshake", "errors": errors, "submit": "सुरक्षित गर्नुहोस्",
        "note": f"स्वीकृत प्रस्ताव रु. {sn.money(limit)} — सम्झौता रकम यसभन्दा बढी हुन सक्दैन।",
        "sections": [{"title": "सम्झौता", "icon": "file-contract", "fields": [
            F("order_no", "सम्झौता / पत्र नं.", v("order_no", m.order_no), required=False),
            F("order_date", "सम्झौता मिति", v("order_date", to_bs(m.order_date) if m.order_date else to_bs(date.today())), kind="date"),
            F("due_date", "काम सम्पन्न गर्नुपर्ने मिति", v("due_date", to_bs(m.due_date) if m.due_date else ""), kind="date"),
            F("order_amount", "सम्झौता रकम (रु.)", v("order_amount", plain(m.order_amount or limit))),
            F("cost_share", "संस्थाको लागत सहभागिता (रु., ऐच्छिक)", v("cost_share", plain(m.cost_share) if m.cost_share else ""),
              required=False, hint="संस्थाले आफ्नो तर्फबाट व्यहोर्ने रकम — सम्झौतामा उल्लेख हुन्छ"),
        ]}],
    })


# ---------------------------------------------------------------- ऐच्छिक: किस्ता भुक्तानी
def _tax_fields(v):
    return [F(k, f"{lbl} (रु.)", v(k, ""), required=False) for k, lbl in mn.TAX_FIELDS]


def _taxes(f):
    taxes = {}
    for k, lbl in mn.TAX_FIELDS:
        t = f.amount(k, lbl, required=False, positive=False)
        if t:
            taxes[k] = str(t)
    return taxes


@login_required
def installment(request, project_id):
    if (r := _guard(request)):
        return r
    from .budget import check_payment
    from .budget import spent as budget_spent

    project = _project(request, project_id)
    m = _m(project)
    if m is None or not m.order_date or m.completed_on or mn.final_payment(m):
        messages.error(request, "किस्ता भुक्तानी सम्झौतापछि र काम सम्पन्न प्रतिवेदनअघि मात्र।")
        return redirect(_next(request, project))
    paid = mn.paid(m, True)
    errors = []
    if request.method == "POST":
        f = Form(request)
        on = f.day("date", "भुक्तानी मिति")
        gross = f.amount("gross", "किस्ता रकम")
        bill = f.text("bill_no", "बिल / भौचर नं.", required=False)
        remarks = f.text("remarks", "कैफियत / प्रगति", required=False)
        taxes = _taxes(f)
        errors = f.errors
        if on and on < m.order_date:
            errors.append("भुक्तानी मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if gross is not None:
            if paid + gross > sn.D(m.order_amount) + mn.TOL:
                errors.append(f"कुल किस्ता रु. {sn.money(paid + gross)} सम्झौता रकम रु. {sn.money(m.order_amount)} भन्दा बढी भयो।")
            if mn.tax_total(taxes) > gross:
                errors.append("कट्टी किस्ता रकमभन्दा बढी भयो।")
            if not errors and (e := check_payment(project, budget_spent(project) + gross, "यो किस्ता")):
                errors.append(e)
        if not errors:
            pay = MinorPayment.objects.create(minor=m, kind="running", date=on, gross=gross, taxes=taxes,
                                              net=gross - mn.tax_total(taxes), bill_no=bill, remarks=remarks,
                                              doc=request.FILES.get("doc"), created_by=request.user)
            if paid + gross > sn.D(m.order_amount) * Decimal("0.9"):
                messages.warning(request, "किस्ता सम्झौता रकमको ९०% नाघ्यो — बाँकी अन्तिम बिलमा।")
            messages.success(request, f"किस्ता रु. {sn.money(gross)} (खुद रु. {sn.money(pay.net)}) दर्ता भयो। "
                                      "टिप्पणी कार्यप्रवाहबाट छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    return _render_form(request, project, {
        "title": "किस्ता भुक्तानी", "icon": "wallet", "errors": errors, "upload": True, "submit": "सुरक्षित गर्नुहोस्",
        "note": f"सम्झौता रकम रु. {sn.money(m.order_amount)} · भुक्तानी भइसकेको रु. {sn.money(paid)} · "
                f"बाँकी रु. {sn.money(sn.D(m.order_amount) - paid)}",
        "sections": [
            {"title": "किस्ता", "icon": "money-bill-wave", "fields": [
                F("date", "भुक्तानी मिति", v("date", to_bs(date.today())), kind="date"),
                F("gross", "किस्ता रकम (रु.)", v("gross")),
                F("bill_no", "बिल / भौचर नं.", v("bill_no"), required=False),
                F("remarks", "प्रगति / कैफियत", v("remarks"), required=False, kind="textarea", wide=True),
                F("doc", "प्रगति प्रतिवेदन / बिल (स्क्यान)", kind="file", required=False),
            ]},
            {"title": "कट्टी", "icon": "receipt", "fields": _tax_fields(v)},
        ],
    })


# ---------------------------------------------------------------- ५. काम सम्पन्न प्रतिवेदन
@login_required
def completion(request, project_id):
    if (r := _guard(request)):
        return r
    project = _project(request, project_id)
    m = _m(project)
    if m is None or not m.order_date:
        messages.error(request, "सम्झौतापछि मात्र काम सम्पन्न प्रतिवेदन।")
        return redirect(_next(request, project))
    if mn.final_payment(m):
        messages.error(request, "अन्तिम बिल भइसकेपछि प्रतिवेदन बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    paid = mn.paid(m, True)
    errors = []
    if request.method == "POST":
        f = Form(request)
        on = f.day("completed_on", "काम सम्पन्न मिति")
        value = f.amount("completion_value", "जाँचपास / स्वीकृत खर्च रकम")
        note = f.text("completion_note", "प्रतिवेदनको सार")
        errors = f.errors
        if on and on < m.order_date:
            errors.append("सम्पन्न मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if value is not None:
            if value > sn.D(m.order_amount) + mn.TOL:
                errors.append(f"जाँचपास रकम सम्झौता रकम रु. {sn.money(m.order_amount)} भन्दा बढी हुन सक्दैन।")
            elif value < paid - mn.TOL:
                errors.append(f"जाँचपास रकम अहिलेसम्मको किस्ता रु. {sn.money(paid)} भन्दा कम हुन सक्दैन।")
        if not errors:
            m.completed_on, m.completion_value, m.completion_note = on, value, note
            if request.FILES.get("completion_doc"):
                m.completion_doc = request.FILES["completion_doc"]
            m.save()
            if m.due_date and on > m.due_date:
                messages.warning(request, f"तोकिएको मिति ({bs_date(m.due_date)}) भन्दा {sn.np((on - m.due_date).days)} दिन ढिला सम्पन्न।")
            messages.success(request, "काम सम्पन्न प्रतिवेदन दर्ता भयो। अब अन्तिम बिल भर्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    return _render_form(request, project, {
        "title": "काम सम्पन्न प्रतिवेदन र जाँचपास", "icon": "clipboard-check", "errors": errors, "upload": True,
        "submit": "सुरक्षित गर्नुहोस्",
        "note": f"सम्झौता रकम रु. {sn.money(m.order_amount)}" + (f" · किस्ता भुक्तानी रु. {sn.money(paid)}" if paid else ""),
        "sections": [{"title": "प्रतिवेदन", "icon": "clipboard-list", "fields": [
            F("completed_on", "काम सम्पन्न मिति", v("completed_on", to_bs(m.completed_on) if m.completed_on else to_bs(date.today())),
              kind="date"),
            F("completion_value", "जाँचपास / स्वीकृत खर्च रकम (रु.)",
              v("completion_value", plain(m.completion_value or m.order_amount))),
            F("completion_doc", "प्रतिवेदन / अनुगमन (स्क्यान)", kind="file", required=False),
            F("completion_note", "प्रतिवेदनको सार — के काम भयो, लाभग्राही, अनुगमनको निष्कर्ष",
              v("completion_note", m.completion_note), kind="textarea", wide=True),
        ]}],
    })


# ---------------------------------------------------------------- ६. अन्तिम बिल
@login_required
def final(request, project_id):
    if (r := _guard(request)):
        return r
    from .budget import check_payment
    from .budget import spent as budget_spent

    project = _project(request, project_id)
    m = _m(project)
    if m is None or not m.completed_on:
        messages.error(request, "पहिले काम सम्पन्न प्रतिवेदन दर्ता गर्नुहोस्।")
        return redirect(_next(request, project))
    if m.prints.filter(doc_type="payment").exists():
        messages.error(request, "अन्तिम भुक्तानी टिप्पणी छापिइसकेकाले अन्तिम बिल बदल्न मिल्दैन।")
        return redirect(_next(request, project))
    fin = mn.final_payment(m)
    paid = mn.paid(m, True)
    remaining = sn.D(m.completion_value) - paid
    errors = []
    if request.method == "POST":
        f = Form(request)
        on = f.day("date", "भुक्तानी मिति")
        gross = f.amount("gross", "अन्तिम बिल रकम")
        bill = f.text("bill_no", "बिल / भौचर नं.", required=False)
        taxes = _taxes(f)
        errors = f.errors
        if on and on < m.completed_on:
            errors.append("अन्तिम भुक्तानी मिति काम सम्पन्न मितिभन्दा अघि हुन सक्दैन।")
        if gross is not None:
            if gross > remaining + mn.TOL:
                errors.append(f"अन्तिम बिल बाँकी रकम रु. {sn.money(remaining)} (जाँचपास − किस्ता) भन्दा बढी हुन सक्दैन।")
            if mn.tax_total(taxes) > gross:
                errors.append("कट्टी बिल रकमभन्दा बढी भयो।")
            if not errors and (e := check_payment(project, budget_spent(project) - (sn.D(fin.gross) if fin else 0) + gross,
                                                  "अन्तिम बिल")):
                errors.append(e)
        if not errors:
            with transaction.atomic():
                obj = fin or MinorPayment(minor=m, kind="final", created_by=request.user)
                obj.date, obj.gross, obj.taxes, obj.bill_no = on, gross, taxes, bill
                obj.net = gross - mn.tax_total(taxes)
                if request.FILES.get("doc"):
                    obj.doc = request.FILES["doc"]
                obj.save()
                project.status = 2
                project.save(update_fields=["status"])
            messages.success(request, f"अन्तिम बिल सुरक्षित भयो — खुद भुक्तानी रु. {sn.money(obj.net)}। भौतिक उपलब्धि भरेर "
                                      "अन्तिम भुक्तानी टिप्पणी छाप्नुहोस्।")
            return redirect(_next(request, project))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    tv = lambda k: p.get(k, fin.taxes.get(k, "") if fin else "")  # noqa: E731
    return _render_form(request, project, {
        "title": "अन्तिम बिल / भुक्तानी", "icon": "wallet", "errors": errors, "upload": True, "submit": "सुरक्षित गर्नुहोस्",
        "note": f"जाँचपास रु. {sn.money(m.completion_value)}" + (f" − किस्ता रु. {sn.money(paid)}" if paid else "") +
                f" = बाँकी रु. {sn.money(remaining)}",
        "sections": [
            {"title": "अन्तिम बिल", "icon": "file-invoice-dollar", "fields": [
                F("date", "भुक्तानी मिति", v("date", to_bs(fin.date) if fin else to_bs(date.today())), kind="date"),
                F("gross", "अन्तिम बिल रकम (रु.)", v("gross", plain(fin.gross) if fin else plain(remaining))),
                F("bill_no", "बिल / भौचर नं.", v("bill_no", fin.bill_no if fin else ""), required=False),
                F("doc", "बिल / भरपाई (स्क्यान)", kind="file", required=False),
            ]},
            {"title": "कट्टी (अग्रिम आयकर, भ्याट, धरौटी)", "icon": "receipt",
             "fields": [F(k, f"{lbl} (रु.)", tv(k), required=False) for k, lbl in mn.TAX_FIELDS]},
        ],
    })


# ---------------------------------------------------------------- छाप्ने
@login_required
def print_doc(request, project_id, doc):
    if not has_perm(request.user, "minor.print"):
        messages.error(request, "यो कागजात छाप्ने अनुमति तपाईंलाई छैन।")
        return redirect("sanstha_workflow")
    project = _project(request, project_id)
    m = _m(project)
    payment = None
    if doc == "installment" and m is not None:
        payment = m.payments.exclude(kind="final").filter(id=request.GET.get("pay") or 0).first()
    if (problem := sn.print_problem(m, doc, payment)):
        messages.error(request, f"“{project.name}”: {problem}")
        return redirect(with_open(reverse("sanstha_workflow"), project.id))
    MinorPrint.objects.create(minor=m, doc_type=doc, printed_by=request.user)
    from .procurement import METHODS

    lab = dict(mn.TAX_FIELDS)
    fin = mn.final_payment(m)
    inst = sn.installments(m)
    shown = payment or fin
    return render(request, "projects/sanstha_print.html", {
        "project": project, "m": m, "doc": doc, "law": METHODS["sanstha"]["law"],
        "invited": list(m.invited.all()), "ranked": sn.ranked(m), "rec": sn.recommended(m), "fin": fin,
        "payment": payment, "inst": inst, "prev": [p for p in inst if payment is None or p.id < payment.id],
        "prev_total": sum((sn.D(p.gross) for p in inst if payment is None or p.id < payment.id), sn.ZERO),
        "taxes": [(lab.get(k, k), sn.D(v)) for k, v in (shown.taxes.items() if shown else [])],
        "today": date.today(), "back": with_open(reverse("sanstha_workflow"), project.id),
        "days": (m.submission_deadline - m.notice_date).days if m.submission_deadline and m.notice_date else None,
    })
