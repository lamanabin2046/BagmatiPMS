"""राजस्व आम्दानी — सूची, चरण panel, हरेक चरणको फारम, स्वीकृति (modal) र छाप्ने कागजात.

चरणको नियम: projects/revenue.py. फारम ढाँचा बोलपत्र / दरभाउपत्रकै (biddings/wf_form.html).
"""
import os
from datetime import date, timedelta
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
from accounts.permissions import user_perms
from biddings.views_workflow import F, Form, plain, to_ad, to_bs
from usercommittee.workflow import approver_identity, bs_date

from . import firms as fm
from . import revenue as rv
from .models import (FiscalYear, RevenueBid, RevenueDoc, RevenueExtraction, RevenueInspection, RevenueInstalment,
                     RevenueOnlineBid, RevenuePayment, RevenuePrint, RevenueRetender, RevenueSource)

VIEW = {"rev.view", "rev.manage", "rev.survey", "rev.approve", "rev.collect", "rev.print"}
UPLOAD_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".kml", ".kmz"}
UPLOAD_MAX = 10 * 1024 * 1024
BID_ROWS = 5


def _user_wards(user):
    from usercommittee.views_workflow import _user_wards as uw

    return uw(user)


def _scoped(request):
    qs = rv.queryset()
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    return qs, wards


def _source(request, sid):
    return get_object_or_404(_scoped(request)[0], id=sid)


def _guard(request, *perms):
    if not user_perms(request.user) & set(perms):
        messages.error(request, "यो काम गर्ने अनुमति तपाईंलाई छैन।")
        return redirect("revenue_list")
    return None


def with_open(url, sid):
    from urllib.parse import parse_qsl, urlencode

    parts = urlparse(url)
    if parts.path.rstrip("/") != reverse("revenue_list").rstrip("/"):
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "open"]
    q.append(("open", str(sid)))
    return parts.path + "?" + urlencode(q)


def _next(request, s):
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return with_open(reverse("revenue_list"), s.id)


def _return_to(request):
    current = urlparse(request.headers.get("HX-Current-URL", ""))
    if current.path:
        return current.path + ("?" + current.query if current.query else "")
    return reverse("revenue_list")


def _cards(s):
    cards = [{"label": "प्रकार", "value": s.get_category_display(), "sub": f"आ.व. {s.fiscalyear.name}"}]
    if s.est_revenue:
        cards.append({"label": "अनुमानित राजस्व", "value": f"रु. {rv.money(s.est_revenue)}"})
        cards.append({"label": "न्यूनतम कबोल", "value": f"रु. {rv.money(s.min_bid)}", "brand": True})
    if s.selected:
        cards.append({"label": "सफल बोलपत्रदाता", "value": s.selected.name, "sub": f"रु. {rv.money(s.selected.amount)}"})
    return cards


def _render_form(request, s, ctx):
    return render(request, "biddings/wf_form.html", {
        "module_label": rv.LABEL, "project": s, "cards": _cards(s) if s.id else [],
        "next": request.POST.get("next") or request.GET.get("next", ""),
        "back": _next(request, s) if s.id else reverse("revenue_list"),
    } | ctx)


def _uploads(request, s, mapping, errors):
    """mapping {field: kind} — मान्य फाइल मात्र; त्रुटि errors मा."""
    files = []
    for field, kind in mapping.items():
        f = request.FILES.get(field)
        if not f:
            continue
        if os.path.splitext(f.name)[1].lower() not in UPLOAD_EXT:
            errors.append(f"{f.name}: PDF, JPG, PNG, KML वा KMZ मात्र।")
        elif f.size > UPLOAD_MAX:
            errors.append(f"{f.name}: १० MB भन्दा ठूलो।")
        else:
            files.append((kind, f))
    return files


def _log(request, s, action, note):
    from usercommittee.models import ActivityLog

    try:
        ActivityLog.objects.create(user=request.user, action=action, model_name="राजस्व ठेक्का", object_id=s.id,
                                   object_repr=str(s)[:250], project_name=s.name[:250], note=note[:250])
    except Exception:
        pass


# ---------------------------------------------------------------- सूची र panel
@login_required
def revenue_list(request):
    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    qs, wards = _scoped(request)
    f = {k: (request.GET.get(k) or "").strip() for k in ("q", "ward", "fiscalyear", "category", "stage")}
    if f["q"]:
        qs = qs.filter(Q(name__icontains=f["q"]) | Q(location__icontains=f["q"]) | Q(bids__name__icontains=f["q"])).distinct()
    if f["ward"].isdigit():
        qs = qs.filter(ward_id=f["ward"])
    if f["fiscalyear"].isdigit():
        qs = qs.filter(fiscalyear_id=f["fiscalyear"])
    if f["category"] in dict(RevenueSource.CATEGORIES):
        qs = qs.filter(category=f["category"])
    approver = "rev.approve" in P
    rows = []
    counts = {"all": 0, "to_approve": 0, "overdue": 0, "completed": 0, "est": rv.ZERO, "contract": rv.ZERO,
              "collected": rv.ZERO, "outstanding": rv.ZERO}
    for s in qs:
        steps, sm = rv.workflow(s, request.user)
        waiting = approver and sm["current_key"] in ("approval", "award")
        ms = sm["money"]
        counts["all"] += 1
        counts["to_approve"] += waiting
        counts["overdue"] += sm["overdue"]
        counts["completed"] += sm["completed"]
        counts["est"] += rv.D(s.est_revenue)
        counts["contract"] += rv.D(s.contract_amount)
        counts["collected"] += ms["paid"]
        counts["outstanding"] += ms["outstanding"] if not s.settled_on else rv.ZERO
        st = f["stage"]
        if (st == "to_approve" and not waiting) or (st == "overdue" and not sm["overdue"]) \
                or (st == "completed" and not sm["completed"]) or (st == "running" and sm["completed"]):
            continue
        if st and st not in ("to_approve", "overdue", "completed", "running") and sm["current_key"] != st:
            continue
        rows.append({"s": s, "cells": rv.row_cells(steps), "summary": sm, "waiting_me": waiting})
    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    f["per_page"] = per_page if per_page in (10, 25, 50, 100) else 25
    page = Paginator(rows, f["per_page"]).get_page(request.GET.get("page"))
    page_rows = list(page.object_list)
    open_id = request.GET.get("open", "")
    open_id = int(open_id) if open_id.isdigit() else None
    if open_id and not any(r["s"].id == open_id for r in page_rows):
        row = next((r for r in rows if r["s"].id == open_id), None)
        if row is None and (s := _scoped(request)[0].filter(id=open_id).first()):
            steps, sm = rv.workflow(s, request.user)
            row = {"s": s, "cells": rv.row_cells(steps), "summary": sm, "waiting_me": False}
        if row:
            page_rows.insert(0, row)
        else:
            open_id = None
    keep = request.GET.copy()
    keep.pop("page", None)
    keep.pop("open", None)
    return render(request, "projects/revenue_list.html", {
        "page": page, "rows": page_rows, "open_id": open_id, "columns": rv.COLUMNS, "counts": counts, "f": f,
        "wards": Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all(),
        "fiscal_years": FiscalYear.objects.order_by("-name"), "categories": RevenueSource.CATEGORIES,
        "keep_qs": keep.urlencode(), "is_approver": approver, "can_manage": "rev.manage" in P,
    })


@login_required
def revenue_detail(request, sid):
    if not user_perms(request.user) & VIEW:
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>अनुमति छैन।</div>", status=403)
    s = _source(request, sid)
    steps, summary = rv.workflow(s, request.user)
    rv.with_next(steps, with_open(_return_to(request), s.id), summary)
    focus = request.GET.get("step")
    return render(request, "projects/_revenue_detail.html", {
        "s": s, "steps": steps, "summary": summary, "docs": list(s.docs.all()),
        "can_print": "rev.print" in user_perms(request.user),
        "focus": int(focus) if focus and focus.isdigit() else summary["current"],
    })


# ---------------------------------------------------------------- १. स्रोत दर्ता
def _source_form(request, s):
    is_new = s.id is None
    errors = []
    if request.method == "POST":
        f = Form(request)
        name = f.text("name", "राजस्व स्रोतको नाम")
        category = request.POST.get("category", "")
        fy = FiscalYear.objects.filter(id=request.POST.get("fiscalyear") or 0).first()
        ward = Ward.objects.filter(id=request.POST.get("ward") or 0).first()
        months = f.amount("contract_months", "ठेक्का अवधि (महिना)")
        errors = f.errors
        if category not in dict(RevenueSource.CATEGORIES):
            errors.append("राजस्व स्रोतको प्रकार छान्नुहोस्।")
        if fy is None:
            errors.append("आर्थिक वर्ष छान्नुहोस्।")
        if months is not None and not (1 <= months <= 60):
            errors.append("ठेक्का अवधि १ देखि ६० महिनासम्म।")
        wards = _user_wards(request.user)
        if wards is not None and (ward is None or ward.id not in wards):
            errors.append("आफ्नो वडाको स्रोत मात्र दर्ता गर्न मिल्छ।")
        if fy and name and RevenueSource.objects.filter(fiscalyear=fy, name=name).exclude(id=s.id).exists():
            errors.append(f"आ.व. {fy.name} मा “{name}” पहिले नै दर्ता छ।")
        if not errors:
            s.name, s.category, s.fiscalyear, s.ward = name, category, fy, ward
            s.location = f.text("location", "स्थान", required=False)
            s.boundary = f.text("boundary", "सीमाना", required=False)
            s.unit = f.text("unit", "एकाइ", required=False) or rv.UNITS.get(category, "")
            s.description = f.text("description", "विवरण", required=False)
            s.contract_months = int(months)
            if not is_new and request.POST.get("status") in dict(RevenueSource.STATUS):
                s.status = request.POST["status"]
            if is_new:
                s.created_by = request.user
            s.save()
            _log(request, s, "create" if is_new else "update", "स्रोत दर्ता")
            messages.success(request, f"“{s.name}” {'दर्ता' if is_new else 'सम्पादन'} भयो।" +
                             (" अब प्राविधिक सर्वेक्षण भर्नुहोस्।" if rv.needs_survey(s) and is_new else ""))
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    fy_default = s.fiscalyear_id or (FiscalYear.objects.order_by("-name").values_list("id", flat=True).first())
    wards = _user_wards(request.user)
    ward_opts = [("", "—")] + [(str(w.id), f"वडा नं. {w.name}") for w in
                               (Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all())]
    fields = [
        F("name", "राजस्व स्रोतको नाम", v("name", s.name), hint="जस्तै: त्रिशूली नदी खण्ड — ढुङ्गा, गिट्टी, बालुवा"),
        F("category", "प्रकार", v("category", s.category), kind="select", options=[("", "— छान्नुहोस् —")] + list(RevenueSource.CATEGORIES)),
        F("fiscalyear", "आर्थिक वर्ष", v("fiscalyear", str(fy_default or "")), kind="select",
          options=[(str(x.id), x.name) for x in FiscalYear.objects.order_by("-name")]),
        F("ward", "वडा", v("ward", str(s.ward_id or "")), kind="select", options=ward_opts, required=False),
        F("location", "स्थान", v("location", s.location), required=False),
        F("unit", "एकाइ", v("unit", s.unit), required=False, hint="नदीजन्य: घन मिटर; अरू: वर्ष / महिना"),
        F("contract_months", "ठेक्का अवधि (महिना)", v("contract_months", s.contract_months or 12)),
        F("boundary", "सीमाना / क्षेत्र (चार किल्ला, निर्देशाङ्क)", v("boundary", s.boundary), kind="textarea", wide=True, required=False),
        F("description", "विवरण / पछिल्ला वर्षको आम्दानी", v("description", s.description), kind="textarea", wide=True, required=False),
    ]
    if not is_new:
        fields.insert(3, F("status", "स्थिति", v("status", s.status), kind="select", options=list(RevenueSource.STATUS)))
    return _render_form(request, s, {
        "title": "नयाँ राजस्व स्रोत दर्ता" if is_new else "राजस्व स्रोत सम्पादन", "icon": "landmark", "errors": errors,
        "submit": "सुरक्षित गर्नुहोस्", "sections": [{"title": "स्रोतको विवरण", "icon": "map-location-dot", "fields": fields}],
        "note": "नदीजन्य पदार्थमा प्राविधिक सर्वेक्षण र वातावरणीय (IEE / EIA) स्वीकृति अनिवार्य हुन्छ।",
    })


@login_required
def revenue_add(request):
    if (r := _guard(request, "rev.manage")):
        return r
    return _source_form(request, RevenueSource(contract_months=12))


@login_required
def revenue_edit(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    if s.approved_at:
        messages.error(request, "स्वीकृत भइसकेपछि स्रोत विवरण बदल्न मिल्दैन।")
        return redirect(_next(request, s))
    return _source_form(request, s)


# ---------------------------------------------------------------- २. प्राविधिक सर्वेक्षण
@login_required
def survey(request, sid):
    if (r := _guard(request, "rev.survey", "rev.manage")):
        return r
    s = _source(request, sid)
    if s.approved_at:
        messages.error(request, "प्रशासनिक स्वीकृतिपछि सर्वेक्षण बदल्न मिल्दैन।")
        return redirect(_next(request, s))
    required = rv.needs_survey(s)
    errors = []
    if request.method == "POST":
        f = Form(request)
        day = f.day("survey_date", "सर्वेक्षण मिति")
        who = f.text("surveyor", "सर्वेक्षण गर्ने प्राविधिक / टोली")
        qty = f.amount("survey_quantity", "उपलब्ध परिमाण", required=required)
        area = f.text("permitted_area", "अनुमति क्षेत्र", required=required)
        env = request.POST.get("env_type", "")
        env_ref = f.text("env_ref", "वातावरणीय स्वीकृति निर्णय", required=required)
        env_on = f.day("env_approved_on", "वातावरणीय स्वीकृति मिति", required=required)
        env_until = f.day("env_valid_until", "स्वीकृतिको म्याद", required=False)
        remarks = f.text("survey_remarks", "कैफियत", required=False)
        errors = f.errors
        if env not in dict(RevenueSource.ENV_TYPES):
            env = ""
        if required and not env:
            errors.append("नदीजन्य पदार्थमा IEE / EIA (वा BES) छान्नुहोस्।")
        if env_on and env_until and env_until <= env_on:
            errors.append("स्वीकृतिको म्याद स्वीकृति मितिभन्दा पछि हुनुपर्छ।")
        if day and day > date.today():
            errors.append("सर्वेक्षण मिति भविष्यको हुन सक्दैन।")
        files = _uploads(request, s, {"doc_survey": "survey", "doc_map": "map", "doc_photo": "photo", "doc_env": "env"}, errors)
        if required and not errors and not (s.docs.filter(kind="survey").exists() or any(k == "survey" for k, _f in files)):
            errors.append("सर्वेक्षण प्रतिवेदन (स्क्यान) अपलोड गर्नुहोस्।")
        if required and env and not errors and not (s.docs.filter(kind="env").exists() or any(k == "env" for k, _f in files)):
            errors.append("वातावरणीय स्वीकृतिको पत्र अपलोड गर्नुहोस्।")
        if not errors:
            s.survey_date, s.surveyor, s.survey_quantity, s.permitted_area = day, who, qty or None, area
            s.env_type, s.env_ref, s.env_approved_on, s.env_valid_until, s.survey_remarks = env, env_ref, env_on, env_until, remarks
            with transaction.atomic():
                s.save()
                for kind, fobj in files:
                    RevenueDoc.objects.create(source=s, kind=kind, file=fobj)
            _log(request, s, "update", "प्राविधिक सर्वेक्षण")
            if env_until and env_until < date.today() + timedelta(days=60):
                messages.warning(request, f"वातावरणीय स्वीकृतिको म्याद {bs_date(env_until)} मा सकिँदैछ।")
            messages.success(request, "प्राविधिक सर्वेक्षण सुरक्षित भयो। अब राजस्व मूल्याङ्कन गर्नुहोस्।")
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    bsx = lambda d: to_bs(d) if d else ""  # noqa: E731
    have = ", ".join(f"{d.get_kind_display()}" for d in s.docs.all()) or "छैन"
    return _render_form(request, s, {
        "title": "प्राविधिक सर्वेक्षण", "icon": "ruler-combined", "errors": errors, "upload": True, "submit": "सुरक्षित गर्नुहोस्",
        "note": ("नदीजन्य पदार्थ: उपलब्ध परिमाण, अनुमति क्षेत्र, सर्वेक्षण प्रतिवेदन र IEE / EIA स्वीकृति अनिवार्य।" if required
                 else "यस प्रकारको स्रोतमा सर्वेक्षण ऐच्छिक।") + f" अपलोड भइसकेका: {have}",
        "sections": [
            {"title": "सर्वेक्षण", "icon": "mountain", "fields": [
                F("survey_date", "सर्वेक्षण मिति", v("survey_date", bsx(s.survey_date) or to_bs(date.today())), kind="date"),
                F("surveyor", "सर्वेक्षण गर्ने प्राविधिक / टोली", v("surveyor", s.surveyor)),
                F("survey_quantity", f"उपलब्ध परिमाण ({s.unit or 'एकाइ'})", v("survey_quantity", plain(s.survey_quantity)), required=required),
                F("permitted_area", "उत्खनन / सञ्चालन गर्न अनुमति क्षेत्र (चेनेज, निर्देशाङ्क, क्षेत्रफल)", v("permitted_area", s.permitted_area),
                  kind="textarea", wide=True, required=required),
            ]},
            {"title": "वातावरणीय अध्ययन र स्वीकृति", "icon": "leaf", "fields": [
                F("env_type", "अध्ययनको प्रकार", v("env_type", s.env_type), kind="select", options=list(RevenueSource.ENV_TYPES),
                  required=required),
                F("env_ref", "स्वीकृति निर्णय / पत्र नं.", v("env_ref", s.env_ref), required=required),
                F("env_approved_on", "स्वीकृति मिति", v("env_approved_on", bsx(s.env_approved_on)), kind="date", required=required),
                F("env_valid_until", "स्वीकृतिको म्याद", v("env_valid_until", bsx(s.env_valid_until)), kind="date", required=False),
                F("survey_remarks", "कैफियत", v("survey_remarks", s.survey_remarks), kind="textarea", wide=True, required=False),
            ]},
            {"title": "कागजात (PDF / फोटो / KML, १० MB सम्म)", "icon": "paperclip", "fields": [
                F("doc_survey", "सर्वेक्षण प्रतिवेदन", kind="file", required=False),
                F("doc_map", "नक्सा", kind="file", required=False),
                F("doc_photo", "फोटो", kind="file", required=False),
                F("doc_env", "वातावरणीय स्वीकृति पत्र", kind="file", required=False),
            ]},
        ],
    })


# ---------------------------------------------------------------- ३. राजस्व मूल्याङ्कन
@login_required
def estimate(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    if s.approved_at:
        messages.error(request, "स्वीकृत भइसकेपछि मूल्याङ्कन बदल्न मिल्दैन।")
        return redirect(_next(request, s))
    if not rv.survey_done(s):
        messages.error(request, "पहिले प्राविधिक सर्वेक्षण भर्नुहोस्।")
        return redirect(_next(request, s))
    errors = []
    if request.method == "POST":
        f = Form(request)
        qty = f.amount("est_quantity", "अनुमानित परिमाण")
        rate = f.amount("rate", "दर")
        min_bid = f.amount("min_bid", "न्यूनतम कबोल अङ्क")
        day = f.day("estimate_date", "मूल्याङ्कन मिति")
        basis = f.text("estimate_note", "दरको आधार")
        errors = f.errors
        est = (qty * rate).quantize(Decimal("0.01")) if qty is not None and rate is not None else None
        if rv.needs_survey(s) and qty is not None and s.survey_quantity and qty > rv.D(s.survey_quantity):
            errors.append(f"अनुमानित परिमाण सर्वेक्षणमा उपलब्ध {rv.money(s.survey_quantity)} {s.unit} भन्दा बढी हुन सक्दैन।")
        if est is not None and min_bid is not None and min_bid < est and not (request.POST.get("low_reason") or "").strip():
            errors.append(f"न्यूनतम कबोल अनुमानित राजस्व रु. {rv.money(est)} भन्दा कम राख्दा कारण लेख्नुहोस्।")
        if not errors:
            s.est_quantity, s.rate, s.est_revenue, s.min_bid, s.estimate_date = qty, rate, est, min_bid, day
            low = (request.POST.get("low_reason") or "").strip()
            s.estimate_note = basis + (f"\nन्यूनतम कबोल कम राख्नुको कारण: {low}" if low and min_bid < est else "")
            s.returned_remarks = ""
            s.save()
            _log(request, s, "update", f"राजस्व मूल्याङ्कन रु. {est}")
            messages.success(request, f"अनुमानित राजस्व रु. {rv.money(est)} · न्यूनतम कबोल रु. {rv.money(min_bid)}। "
                                      "मूल्याङ्कन टिप्पणी छापी स्वीकृतिका लागि पठाउनुहोस्।")
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    return _render_form(request, s, {
        "title": "राजस्व मूल्याङ्कन", "icon": "calculator", "errors": errors, "submit": "सुरक्षित गर्नुहोस्",
        "note": "अनुमानित राजस्व = अनुमानित परिमाण × स्वीकृत दर (आफैँ हिसाब हुन्छ)।" +
                (f" सर्वेक्षणमा उपलब्ध: {rv.money(s.survey_quantity)} {s.unit}" if s.survey_quantity else ""),
        "sections": [{"title": "हिसाब", "icon": "calculator", "fields": [
            F("est_quantity", f"अनुमानित परिमाण ({s.unit or 'एकाइ'})", v("est_quantity", plain(s.est_quantity) or plain(s.survey_quantity))),
            F("rate", "स्वीकृत दर (रु. प्रति एकाइ)", v("rate", plain(s.rate))),
            F("min_bid", "न्यूनतम कबोल अङ्क (रु.)", v("min_bid", plain(s.min_bid)), hint="सामान्यतया अनुमानित राजस्व बराबर वा बढी"),
            F("estimate_date", "मूल्याङ्कन मिति", v("estimate_date", to_bs(s.estimate_date) if s.estimate_date else to_bs(date.today())),
              kind="date"),
            F("estimate_note", "दरको आधार / हिसाब (सभाबाट पारित दर, जिल्ला दररेट, पछिल्लो ठेक्का…)", v("estimate_note", s.estimate_note),
              kind="textarea", wide=True),
            F("low_reason", "न्यूनतम कबोल अनुमानभन्दा कम भए कारण", v("low_reason"), kind="textarea", wide=True, required=False),
        ]}],
    })


# ---------------------------------------------------------------- ४. प्रशासनिक स्वीकृति (modal)
@login_required
def approve(request, sid):
    s = _source(request, sid)
    P = user_perms(request.user)
    allowed = "rev.approve" in P
    if not allowed and not (s.approved_at and P & VIEW):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>तपाईंलाई स्वीकृत गर्ने अधिकार छैन।</div>", status=403)
    problems, warnings = [], []
    if not s.est_revenue:
        problems.append("राजस्व मूल्याङ्कन भएको छैन।")
    if not rv.survey_done(s):
        problems.append("प्राविधिक सर्वेक्षण बाँकी छ।")
    if (e := rv.env_problem(s)):
        problems.append(e)
    if s.est_revenue and not s.prints.filter(doc_type="estimate").exists():
        warnings.append("मूल्याङ्कन टिप्पणी छापिएको अभिलेख छैन।")
    if s.min_bid and s.est_revenue and s.min_bid < s.est_revenue:
        warnings.append("न्यूनतम कबोल अनुमानित राजस्वभन्दा कम राखिएको छ।")
    if request.method == "POST":
        def fail(msg, code=400):
            return HttpResponse(f"<p class='text-sm text-rose-600'>{msg}</p>", status=code)
        if not allowed:
            return fail("स्वीकृत गर्ने अधिकार छैन।", 403)
        if s.approved_at:
            return fail("पहिले नै स्वीकृत भइसकेको छ।")
        remarks = (request.POST.get("remarks") or "").strip()
        if request.POST.get("decision") == "return":
            if not remarks:
                return fail("फिर्ता पठाउँदा कारण लेख्नुहोस्।")
            s.returned_remarks = remarks
            s.save(update_fields=["returned_remarks"])
            _log(request, s, "update", f"फिर्ता: {remarks}")
            messages.warning(request, f"“{s.name}” सच्याउन फिर्ता पठाइयो।")
        else:
            if problems:
                return fail(" ".join(problems))
            name, post = approver_identity(request.user, "municipal")
            s.approved_by, s.approved_at, s.approver_name = request.user, timezone.now(), f"{name} ({post})"
            s.approval_ref, s.approval_remarks, s.returned_remarks = (request.POST.get("approval_ref") or "").strip(), remarks, ""
            s.save()
            _log(request, s, "update", "प्रशासनिक स्वीकृति")
            messages.success(request, f"“{s.name}” को न्यूनतम कबोल रु. {rv.money(s.min_bid)} स्वीकृत भयो। अब बोलपत्र आह्वान गर्नुहोस्।")
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = with_open(_return_to(request), s.id)
        return resp
    name, post = approver_identity(request.user, "municipal")
    return render(request, "projects/_revenue_approve.html", {
        "s": s, "mode": "approval", "problems": problems, "warnings": warnings, "can_approve": allowed and not s.approved_at,
        "name": name, "post": post, "docs": list(s.docs.all()),
    })


# ---------------------------------------------------------------- ५. बोलपत्र आह्वान
@login_required
def notice(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    if not s.approved_at:
        messages.error(request, "प्रशासनिक स्वीकृति नभई बोलपत्र आह्वान गर्न मिल्दैन।")
        return redirect(_next(request, s))
    if s.bids.filter(round=s.tender_round).exists() or s.online_bids.filter(round=s.tender_round).exists():
        messages.error(request, "बोलपत्र प्राप्त भइसकेपछि आह्वान बदल्न मिल्दैन।")
        return redirect(_next(request, s))
    errors = []
    if request.method == "POST":
        f = Form(request)
        day = f.day("notice_date", "सूचना प्रकाशित मिति")
        deadline = f.day("bid_deadline", "बोलपत्र पेश गर्ने अन्तिम मिति")
        ref = f.text("notice_ref", "सूचना नं.", required=False)
        pct = f.amount("bid_security_pct", "बोलपत्र जमानत (%)")
        cond = f.text("conditions", "योग्यता र शर्त")
        errors = f.errors
        if day and day < s.approved_at.date():
            errors.append("सूचना मिति स्वीकृत मितिभन्दा अघि हुन सक्दैन।")
        if day and deadline and (deadline - day).days < rv.NOTICE_DAYS:
            errors.append(f"बोलपत्र पेश गर्न कम्तीमा {rv.np(rv.NOTICE_DAYS)} दिन दिनुपर्छ (अहिले {rv.np(max((deadline - day).days, 0))} दिन)।")
        if pct is not None and not (0 < pct <= 10):
            errors.append("बोलपत्र जमानत ० देखि १० प्रतिशतसम्म।")
        if not errors:
            s.notice_date, s.bid_deadline, s.notice_ref, s.bid_security_pct, s.conditions = day, deadline, ref, pct, cond
            s.save()
            _log(request, s, "update", "बोलपत्र आह्वान")
            messages.success(request, "बोलपत्र आह्वान सुरक्षित भयो। अब सूचना छापेर प्रकाशन गर्नुहोस्।")
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    default_cond = ("१. कानुनबमोजिम दर्ता भई नवीकरण भएको फर्म / व्यक्ति, PAN / VAT दर्ता र कर चुक्ता प्रमाणपत्र।\n"
                    "२. न्यूनतम कबोल अङ्कभन्दा कम कबोल गरेको बोलपत्र मान्य हुने छैन।\n"
                    "३. कबोल अङ्कको तोकिएको प्रतिशत बराबरको बोलपत्र जमानत (बैंक जमानत वा नगद धरौटी) पेश गर्नुपर्नेछ।\n"
                    "४. सम्झौता हुँदा कार्यसम्पादन जमानत र पहिलो किस्ता बुझाउनुपर्नेछ; बाँकी किस्ता तोकिएको मितिमा।\n"
                    "५. स्वीकृत क्षेत्र र परिमाणभन्दा बढी सङ्कलन / उत्खनन गरेमा जरिवाना र सम्झौता रद्द हुनेछ।\n"
                    "६. कालोसूचीमा परेका फर्म / व्यक्ति सहभागी हुन पाउने छैनन्।")
    return _render_form(request, s, {
        "title": "बोलपत्र आह्वान सूचना", "icon": "bullhorn", "errors": errors, "submit": "सुरक्षित गर्नुहोस्",
        "note": f"स्वीकृत न्यूनतम कबोल रु. {rv.money(s.min_bid)} · बोलपत्र पेश गर्न कम्तीमा {rv.np(rv.NOTICE_DAYS)} दिन",
        "sections": [{"title": "आह्वान", "icon": "bullhorn", "fields": [
            F("notice_date", "सूचना प्रकाशित मिति", v("notice_date", to_bs(s.notice_date) if s.notice_date else to_bs(date.today())), kind="date"),
            F("bid_deadline", "बोलपत्र पेश गर्ने अन्तिम मिति", v("bid_deadline", to_bs(s.bid_deadline) if s.bid_deadline else ""), kind="date"),
            F("notice_ref", "सूचना नं.", v("notice_ref", s.notice_ref), required=False),
            F("bid_security_pct", "बोलपत्र जमानत (कबोल अङ्कको %)", v("bid_security_pct", plain(s.bid_security_pct))),
            F("conditions", "योग्यता, भुक्तानी तालिका र शर्त", v("conditions", s.conditions or default_cond), kind="textarea", wide=True),
        ]}],
    })


# ---------------------------------------------------------------- ६. बोलपत्र खोल्ने र मूल्याङ्कन
@login_required
def bids(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    if not s.notice_date:
        messages.error(request, "पहिले बोलपत्र आह्वान गर्नुहोस्।")
        return redirect(_next(request, s))
    if s.award_at:
        messages.error(request, "सफल बोलपत्रदाता स्वीकृत भइसकेपछि बोलपत्र बदल्न मिल्दैन।")
        return redirect(_next(request, s))
    existing = list(s.bids.filter(round=s.tender_round).order_by("id"))
    sealed_open = bool(s.bid_deadline and date.today() > s.bid_deadline)
    online = [o for o in s.online_bids.filter(round=s.tender_round, imported=False).select_related("bidder")] if sealed_open else []
    sealed_count = s.online_bids.filter(round=s.tender_round).count()
    keys = [f"b{b.id}" for b in existing] + [f"o{o.id}" for o in online] + [f"n{i}" for i in range(BID_ROWS)]
    errors = []
    if request.method == "POST":
        P_ = request.POST
        opened = to_ad(P_.get("opening_date"))
        if opened is None:
            errors.append("बोलपत्र खोलेको मिति भर्नुहोस् (वि.सं. YYYY-MM-DD)।")
        elif opened < s.bid_deadline:
            errors.append("बोलपत्र पेश गर्ने अन्तिम मितिअघि खोल्न मिल्दैन।")
        elif opened > date.today():
            errors.append("खोलेको मिति भविष्यको हुन सक्दैन।")
        items, seen = [], set()
        for k in keys:
            name = (P_.get(f"name_{k}") or "").strip()
            raw = (P_.get(f"amount_{k}") or "").strip()
            if not name and not raw:
                continue
            from biddings.views_workflow import to_dec
            amt = to_dec(raw)
            if not name:
                errors.append("रकम भरेको पङ्क्तिमा बोलपत्रदाताको नाम लेख्नुहोस्।")
                continue
            if amt in (None, "bad") or amt <= 0:
                errors.append(f"“{name}” को कबोल अङ्क मिलेन।")
                continue
            pan = (P_.get(f"pan_{k}") or "").strip()
            if pan and not (pan.isdigit() and len(pan) == 9):
                errors.append(f"“{name}”: PAN ९ अङ्कको हुनुपर्छ।")
            if name in seen:
                errors.append(f"“{name}” दुई पटक लेखिएको छ।")
            seen.add(name)
            if (e := fm.blocked(fm.find(name, pan), name, pan)):
                errors.append(e)
            sec_amt = to_dec(P_.get(f"secamt_{k}"))
            sec_amt = None if sec_amt in (None, "bad") else sec_amt
            sec_ok = bool(P_.get(f"security_{k}"))
            remarks = (P_.get(f"remarks_{k}") or "").strip()
            if sec_ok and sec_amt is not None and sec_amt < rv.security_required(s, amt):
                sec_ok = False
                remarks = (remarks + " · " if remarks else "") + f"जमानत रु. {rv.money(rv.security_required(s, amt))} चाहिनेमा कम"
            items.append({"name": name, "pan": pan, "amount": amt, "address": (P_.get(f"address_{k}") or "").strip(),
                          "security_ok": sec_ok, "eligible": bool(P_.get(f"eligible_{k}")), "remarks": remarks[:250],
                          "security_kind": P_.get(f"seckind_{k}") if P_.get(f"seckind_{k}") in ("cash", "bank") else "",
                          "security_amount": sec_amt, "security_ref": (P_.get(f"secref_{k}") or "").strip()[:200],
                          "online": k.startswith("o") or (k.startswith("b") and k[1:].isdigit() and
                                                           any(b.online for b in existing if str(b.id) == k[1:]))})
        if not items and not errors:
            errors.append("कम्तीमा एउटा बोलपत्र भर्नुहोस्।")
        if not errors:
            with transaction.atomic():
                s.bids.filter(round=s.tender_round).delete()
                for it in items:
                    firm = fm.find_or_create(it["name"], it["pan"], it["address"], kind="revenue")
                    RevenueBid.objects.create(source=s, firm=firm, round=s.tender_round, **it)
                s.online_bids.filter(round=s.tender_round, id__in=[o.id for o in online]).update(imported=True)
                s.opening_date = opened
                s.save(update_fields=["opening_date"])
            _log(request, s, "update", f"{len(items)} बोलपत्र खोलियो")
            rec = rv.recommended(s)
            if rec is None:
                messages.warning(request, "कुनै बोलपत्र मान्य भएन (न्यूनतम कबोल, जमानत वा योग्यता नपुगेको) — पुनः आह्वान गर्नुपर्छ।")
            else:
                messages.success(request, f"बोलपत्र सुरक्षित भयो। उच्चतम मान्य: {rec.name} रु. {rv.money(rec.amount)}। "
                                          "तुलनात्मक विवरण छापी स्वीकृतिका लागि पठाउनुहोस्।")
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else None
    by = {f"b{b.id}": b for b in existing}
    from . import revenue_portal as rp
    for o in online:            # अनलाइन बोलपत्र: म्याद सकिएपछि मात्र सिल खोलिन्छ
        bd = o.bidder
        by[f"o{o.id}"] = RevenueBid(name=bd.name, pan=bd.pan, address=bd.address, amount=rp.unseal(o), eligible=False,
                                    security_ok=False, security_kind=o.security_kind, security_amount=o.security_amount,
                                    security_ref=o.security_ref, remarks=f"अनलाइन · {timezone.localtime(o.submitted_at):%Y-%m-%d %H:%M}"
                                    + " · कागजात र जमानत जाँच्नुहोस्", online=True)
    rows = []
    for k in keys:
        b = by.get(k)
        g = (lambda n, d, k=k: p.get(f"{n}_{k}", "") if p is not None else d)
        o = next((x for x in online if f"o{x.id}" == k), None)
        rows.append({"key": k, "name": g("name", b.name if b else ""), "pan": g("pan", b.pan if b else ""),
                     "address": g("address", b.address if b else ""), "amount": g("amount", plain(b.amount) if b else ""),
                     "security": (bool(p.get(f"security_{k}")) if p is not None else (b.security_ok if b else True)),
                     "eligible": (bool(p.get(f"eligible_{k}")) if p is not None else (b.eligible if b else True)),
                     "remarks": g("remarks", b.remarks if b else ""), "online": bool(b and b.online),
                     "seckind": g("seckind", b.security_kind if b else ""), "secamt": g("secamt", plain(b.security_amount) if b else ""),
                     "secref": g("secref", b.security_ref if b else ""), "docs": [x for x in (o.doc, o.security_doc) if x] if o else []})
    return render(request, "projects/revenue_bids.html", {
        "module_label": rv.LABEL, "s": s, "rows": rows, "errors": errors, "cards": _cards(s), "back": _next(request, s),
        "next": request.POST.get("next") or request.GET.get("next", ""),
        "opening_date": p.get("opening_date") if p is not None else (to_bs(s.opening_date) if s.opening_date else
                                                                   to_bs(max(date.today(), s.bid_deadline))),
        "firm_options": fm.options(["revenue", "contractor", "supplier"]),
        "sealed_count": sealed_count, "sealed_open": sealed_open, "online_new": len(online),
    })


# ---------------------------------------------------------------- ७. सफल बोलपत्रदाता स्वीकृति (modal)
@login_required
def award(request, sid):
    s = _source(request, sid)
    P = user_perms(request.user)
    allowed = "rev.approve" in P
    if not allowed and not (s.award_at and P & VIEW):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>तपाईंलाई स्वीकृत गर्ने अधिकार छैन।</div>", status=403)
    ranked = rv.ranked(s)
    rec = rv.recommended(s)
    problems, warnings = [], []
    if not ranked:
        problems.append("प्राप्त बोलपत्र भरिएको छैन।")
    elif rec is None:
        problems.append("कुनै बोलपत्र मान्य छैन — पुनः आह्वान गर्नुहोस्।")
    if ranked and len(ranked) < 2:
        warnings.append("एउटा मात्र बोलपत्र प्राप्त भएको छ।")
    if ranked and not s.prints.filter(doc_type="comparison").exists():
        warnings.append("तुलनात्मक विवरण छापिएको अभिलेख छैन।")
    if request.method == "POST":
        def fail(msg, code=400):
            return HttpResponse(f"<p class='text-sm text-rose-600'>{msg}</p>", status=code)
        if not allowed:
            return fail("स्वीकृत गर्ने अधिकार छैन।", 403)
        if s.award_at:
            return fail("पहिले नै स्वीकृत भइसकेको छ।")
        if problems:
            return fail(" ".join(problems))
        b = s.bids.filter(id=request.POST.get("bid") or 0).first()
        reason = (request.POST.get("remarks") or "").strip()
        if b is None:
            return fail("सफल बोलपत्रदाता छान्नुहोस्।")
        if not rv.responsive(s, b):
            return fail(f"“{b.name}” को बोलपत्र मान्य छैन (योग्यता, जमानत वा न्यूनतम कबोल)।")
        if b.id != rec.id and not reason:
            return fail("उच्चतम मान्य कबोलबाहेक अर्को छान्दा कारण लेख्नुहोस्।")
        if (e := fm.blocked(b.firm, b.name, b.pan)):
            return fail(e)
        name, post = approver_identity(request.user, "municipal")
        s.selected, s.award_at, s.award_approver, s.award_remarks = b, timezone.now(), f"{name} ({post})", reason
        s.save()
        _log(request, s, "update", f"सफल बोलपत्रदाता: {b.name}")
        messages.success(request, f"{b.name} को रु. {rv.money(b.amount)} को बोलपत्र स्वीकृत भयो। स्वीकृति पत्र छापी सम्झौता गर्नुहोस्।")
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = with_open(_return_to(request), s.id)
        return resp
    name, post = approver_identity(request.user, "municipal")
    return render(request, "projects/_revenue_approve.html", {
        "s": s, "mode": "award", "problems": problems, "warnings": warnings, "can_approve": allowed and not s.award_at,
        "name": name, "post": post, "rows": [{"b": b, "ok": ok} for b, ok in ranked], "rec": rec,
    })


# ---------------------------------------------------------------- ८. सम्झौता
@login_required
def agreement(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    if not s.award_at:
        messages.error(request, "सम्झौता अघि सफल बोलपत्रदाता स्वीकृत हुनुपर्छ।")
        return redirect(_next(request, s))
    if s.instalments.filter(paid_amount__gt=0).exists():
        messages.error(request, "किस्ता असुल भइसकेपछि सम्झौता बदल्न मिल्दैन।")
        return redirect(_next(request, s))
    amount = rv.D(s.selected.amount)
    errors = []
    if request.method == "POST":
        f = Form(request)
        no = f.text("agreement_no", "सम्झौता नं.", required=False)
        signed = f.day("agreement_date", "सम्झौता मिति")
        start = f.day("start_date", "ठेक्का सुरु मिति")
        end = f.day("end_date", "ठेक्का अन्त्य मिति")
        sec = f.amount("security_amount", "कार्यसम्पादन जमानत रकम")
        sec_ref = f.text("security_ref", "जमानत (बैंक र नं. वा धरौटी रसिद)")
        sec_exp = f.day("security_expiry", "जमानतको म्याद")
        n = f.amount("instalments", "किस्ता संख्या")
        errors = f.errors
        if signed and signed < s.award_at.date():
            errors.append("सम्झौता मिति स्वीकृत मितिभन्दा अघि हुन सक्दैन।")
        if start and end and end <= start:
            errors.append("ठेक्का अन्त्य मिति सुरु मितिभन्दा पछि हुनुपर्छ।")
        if signed and start and start < signed:
            errors.append("ठेक्का सुरु मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if n is not None and not (1 <= n <= 12 and n == int(n)):
            errors.append("किस्ता संख्या १ देखि १२ सम्म।")
        if sec_exp and end and sec_exp < end:
            errors.append("कार्यसम्पादन जमानतको म्याद ठेक्का अन्त्य मितिसम्म हुनुपर्छ।")
        files = _uploads(request, s, {"doc_agreement": "agreement"}, errors)
        if not errors:
            with transaction.atomic():
                s.agreement_no, s.agreement_date, s.start_date, s.end_date = no, signed, start, end
                s.contract_amount, s.security_amount, s.security_ref, s.security_expiry = amount, sec, sec_ref, sec_exp
                s.save()
                s.instalments.all().delete()
                for k, due, amt in rv.schedule(start, end, amount, int(n)):
                    RevenueInstalment.objects.create(source=s, n=k, due_date=due, amount=amt)
                for kind, fobj in files:
                    RevenueDoc.objects.create(source=s, kind=kind, file=fobj)
            _log(request, s, "update", f"सम्झौता रु. {amount}")
            messages.success(request, f"सम्झौता र {rv.np(int(n))} किस्ताको तालिका सुरक्षित भयो। सम्झौता पत्र छाप्नुहोस्।")
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    start0 = s.start_date or date.today()
    end0 = s.end_date or (start0 + timedelta(days=round(s.contract_months * 30.4)) - timedelta(days=1))
    bsx = lambda d: to_bs(d) if d else ""  # noqa: E731
    return _render_form(request, s, {
        "title": "सम्झौता र कार्यसम्पादन जमानत", "icon": "handshake", "errors": errors, "upload": True, "submit": "सुरक्षित गर्नुहोस्",
        "note": f"सम्झौता रकम = स्वीकृत कबोल रु. {rv.money(amount)} · पहिलो किस्ता सम्झौतासँगै, बाँकी बराबर अन्तरमा (तालिका आफैँ बन्छ)",
        "sections": [
            {"title": "सम्झौता", "icon": "file-contract", "fields": [
                F("agreement_no", "सम्झौता नं.", v("agreement_no", s.agreement_no), required=False),
                F("agreement_date", "सम्झौता मिति", v("agreement_date", bsx(s.agreement_date) or to_bs(date.today())), kind="date"),
                F("contract_amount", "सम्झौता रकम (रु.)", plain(amount), readonly=True, required=False),
                F("start_date", "ठेक्का सुरु मिति", v("start_date", bsx(start0)), kind="date"),
                F("end_date", "ठेक्का अन्त्य मिति", v("end_date", bsx(end0)), kind="date", hint=f"अवधि {rv.np(s.contract_months)} महिना"),
                F("instalments", "किस्ता संख्या", v("instalments", str(s.instalments.count() or 4))),
            ]},
            {"title": "कार्यसम्पादन जमानत", "icon": "shield-halved", "fields": [
                F("security_amount", "जमानत रकम (रु.)", v("security_amount", plain(s.security_amount) or plain((amount * Decimal("0.1")).quantize(Decimal("1"))))),
                F("security_ref", "बैंक र जमानत नं. / धरौटी रसिद", v("security_ref", s.security_ref)),
                F("security_expiry", "जमानतको म्याद", v("security_expiry", bsx(s.security_expiry) or bsx(end0 + timedelta(days=30))), kind="date"),
                F("doc_agreement", "हस्ताक्षरित सम्झौता (स्क्यान)", kind="file", required=False),
            ]},
        ],
    })


# ---------------------------------------------------------------- ९. राजस्व असुली
@login_required
def collect(request, sid):
    if (r := _guard(request, "rev.collect", "rev.manage")):
        return r
    s = _source(request, sid)
    if not s.agreement_date or s.settled_on or s.cancelled_on:
        messages.error(request, "चालु सम्झौतामा मात्र असुली दर्ता (रद्द भएकोमा बाँकी रकम फरफारकमा बक्यौता हुन्छ)।")
        return redirect(_next(request, s))
    errors = []
    if request.method == "POST":
        i = s.instalments.filter(id=request.POST.get("instalment") or 0).first()
        f = Form(request)
        paid = f.amount("paid_amount", "असुल रकम")
        on = f.day("paid_on", "असुल मिति")
        receipt = f.text("receipt_no", "रसिद नं.")
        fee = f.amount("late_fee", "विलम्ब शुल्क", required=False, positive=False) or rv.ZERO
        errors = f.errors
        if i is not None and paid is not None and on:
            need_fee = rv.late_fee(paid, i.due_date, on)
            if fee < need_fee and not (request.POST.get("fee_reason") or "").strip():
                errors.append(f"विलम्ब शुल्क रु. {rv.money(need_fee)} लाग्छ ({rv.np(rv.months_late(i.due_date, on))} महिना ढिला) — "
                              "कम लिँदा कारण लेख्नुहोस्।")
        if i is None:
            errors.append("किस्ता छान्नुहोस्।")
        elif paid is not None and paid > rv.D(i.amount) - rv.D(i.paid_amount) + Decimal("0.5"):
            errors.append(f"किस्ता {rv.np(i.n)} को बाँकी रु. {rv.money(rv.D(i.amount) - rv.D(i.paid_amount))} भन्दा बढी असुल गर्न मिल्दैन।")
        if on and on > date.today():
            errors.append("असुल मिति भविष्यको हुन सक्दैन।")
        if on and on < s.agreement_date:
            errors.append("असुल मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if receipt and RevenuePayment.objects.filter(receipt_no=receipt).exists():
            errors.append(f"रसिद नं. {receipt} पहिले नै प्रयोग भइसकेको छ।")
        if not errors:
            remarks = (request.POST.get("remarks") or "").strip()
            if (fr := (request.POST.get("fee_reason") or "").strip()):
                remarks = (remarks + " · " if remarks else "") + f"विलम्ब शुल्क छुट: {fr}"
            with transaction.atomic():
                i = RevenueInstalment.objects.select_for_update().get(id=i.id)
                RevenuePayment.objects.create(instalment=i, date=on, amount=paid, late_fee=fee, receipt_no=receipt,
                                              remarks=remarks[:250], created_by=request.user)
                i.paid_amount = rv.D(i.paid_amount) + paid
                i.late_fee_paid = rv.D(i.late_fee_paid) + fee
                i.paid_on, i.receipt_no = on, receipt
                i.save()
            _log(request, s, "update", f"किस्ता {i.n} असुल रु. {paid}" + (f" + विलम्ब शुल्क {fee}" if fee else "") + f", रसिद {receipt}")
            late = (on - i.due_date).days if on and on > i.due_date else 0
            if late and not fee:
                messages.warning(request, f"किस्ता {rv.np(i.n)} {rv.np(late)} दिन ढिला असुल भयो।")
            messages.success(request, f"किस्ता {rv.np(i.n)}: रु. {rv.money(paid)} असुल दर्ता भयो (रसिद {receipt})।")
            return redirect(reverse("revenue_collect", args=[s.id]) + (f"?next={request.POST.get('next')}" if request.POST.get("next") else ""))
    ms = rv.money_status(s)
    today = date.today()
    for i in ms["instalments"]:
        i.fee_now = rv.late_fee(rv.D(i.amount) - rv.D(i.paid_amount), i.due_date, today)
    return render(request, "projects/revenue_collect.html", {"L": rv.settings_(),
        "module_label": rv.LABEL, "s": s, "ms": ms, "errors": errors, "cards": _cards(s), "back": _next(request, s),
        "next": request.POST.get("next") or request.GET.get("next", ""), "today_bs": to_bs(date.today()), "today": date.today(),
        "can_print": "rev.print" in user_perms(request.user), "d": request.POST if request.method == "POST" else {},
    })


# ---------------------------------------------------------------- अनुगमन (ऐच्छिक, सम्झौतापछि)
@login_required
def inspect(request, sid):
    if (r := _guard(request, "rev.survey", "rev.manage")):
        return r
    s = _source(request, sid)
    if not s.agreement_date or s.settled_on:
        messages.error(request, "अनुगमन सम्झौतापछि र फरफारकअघि मात्र।")
        return redirect(_next(request, s))
    errors = []
    if request.method == "POST":
        f = Form(request)
        day = f.day("date", "निरीक्षण मिति")
        who = f.text("inspector", "निरीक्षण गर्ने")
        qty = f.amount("quantity", "सङ्कलन / उत्खनन परिमाण", required=False, positive=False)
        finding = f.text("finding", "निरीक्षणको विवरण")
        violation = f.text("violation", "उल्लङ्घन", required=False)
        penalty = f.amount("penalty", "जरिवाना", required=False, positive=False)
        action = f.text("action", "सुधारात्मक कारबाही", required=False)
        errors = f.errors
        if day and day > date.today():
            errors.append("निरीक्षण मिति भविष्यको हुन सक्दैन।")
        if penalty and not violation:
            errors.append("जरिवाना गर्दा उल्लङ्घनको विवरण लेख्नुहोस्।")
        files = _uploads(request, s, {"doc": "photo"}, errors)
        if not errors:
            ins = RevenueInspection.objects.create(source=s, date=day, inspector=who, quantity=qty or None, finding=finding,
                                                   violation=violation, penalty=penalty or 0, action=action,
                                                   doc=files[0][1] if files else None)
            _log(request, s, "create", f"अनुगमन {day}" + (f", जरिवाना रु. {penalty}" if penalty else ""))
            total = sum((rv.D(q) for q in RevenueInspection.objects.filter(source=s).values_list("quantity", flat=True)), rv.ZERO)
            if s.est_quantity and total > rv.D(s.est_quantity):
                messages.warning(request, f"कुल सङ्कलन {rv.money(total)} {s.unit} — स्वीकृत परिमाण {rv.money(s.est_quantity)} नाघ्यो!")
            messages.success(request, "निरीक्षण प्रतिवेदन दर्ता भयो।" + (f" जरिवाना रु. {rv.money(ins.penalty)} फरफारकअघि असुल गर्नुपर्छ।" if ins.penalty else ""))
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    total = sum((rv.D(x.quantity) for x in s.inspections.all()), rv.ZERO)
    return _render_form(request, s, {
        "title": "सम्झौता अनुगमन / निरीक्षण", "icon": "binoculars", "errors": errors, "upload": True, "submit": "सुरक्षित गर्नुहोस्",
        "note": (f"स्वीकृत परिमाण {rv.money(s.est_quantity)} {s.unit} · अहिलेसम्म सङ्कलन {rv.money(total)} {s.unit}" if s.est_quantity else
                 "क्षेत्र, समय, ढुवानी र शर्त पालना जाँच्नुहोस्।"),
        "sections": [{"title": "निरीक्षण", "icon": "binoculars", "fields": [
            F("date", "निरीक्षण मिति", v("date", to_bs(date.today())), kind="date"),
            F("inspector", "निरीक्षण गर्ने (नाम / टोली)", v("inspector")),
            F("quantity", f"यस अवधिमा सङ्कलन / उत्खनन ({s.unit or 'एकाइ'})", v("quantity"), required=False),
            F("finding", "निरीक्षणको विवरण (क्षेत्र, ढुवानी, शर्त पालना)", v("finding"), kind="textarea", wide=True),
            F("violation", "उल्लङ्घन (भए)", v("violation"), required=False),
            F("penalty", "जरिवाना (रु.)", v("penalty"), required=False),
            F("action", "सुधारात्मक कारबाही / निर्देशन", v("action"), required=False),
            F("doc", "फोटो / मुचुल्का", kind="file", required=False),
        ]}],
    })


# ---------------------------------------------------------------- १०. फरफारक
@login_required
def settle(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    if not s.agreement_date:
        messages.error(request, "सम्झौता भएपछि मात्र फरफारक।")
        return redirect(_next(request, s))
    if s.settled_on:
        messages.error(request, "फरफारक भइसकेको छ।")
        return redirect(_next(request, s))
    ms = rv.money_status(s)
    errors = []
    if request.method == "POST":
        f = Form(request)
        day = f.day("settled_on", "फरफारक मिति")
        remarks = f.text("settlement_remarks", "फरफारकको विवरण")
        release = bool(request.POST.get("security_released"))
        errors = f.errors
        arrears = ms["outstanding"] + ms["late_pending"] if s.cancelled_on else rv.ZERO
        if not s.cancelled_on and ms["outstanding"] > 0:
            errors.append(f"असुल गर्न बाँकी रु. {rv.money(ms['outstanding'])} छ — सबै किस्ता असुल नभई फरफारक हुँदैन।")
        if not s.cancelled_on and ms["late_pending"] > 0:
            errors.append(f"विलम्ब शुल्क रु. {rv.money(ms['late_pending'])} असुल गर्न बाँकी छ।")
        if s.cancelled_on and release:
            errors.append("रद्द भएको सम्झौताको जमानत फिर्ता हुँदैन।")
        if ms["penalty"] and not (request.POST.get("penalty_receipt") or "").strip():
            errors.append(f"अनुगमनमा तोकिएको जरिवाना रु. {rv.money(ms['penalty'])} असुलीको रसिद नं. लेख्नुहोस्।")
        if day and s.agreement_date and day < s.agreement_date:
            errors.append("फरफारक मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if day and s.end_date and day < s.end_date and not s.cancelled_on and not (request.POST.get("early_reason") or "").strip():
            errors.append(f"ठेक्का अवधि ({bs_date(s.end_date)}) सकिनुअघि फरफारक गर्दा कारण लेख्नुहोस्।")
        if not errors:
            extra = []
            if ms["penalty"]:
                extra.append(f"जरिवाना रु. {ms['penalty']:,.0f} असुल (रसिद {request.POST['penalty_receipt'].strip()})")
            if (er := (request.POST.get("early_reason") or "").strip()):
                extra.append(f"अवधिअघि फरफारक: {er}")
            if arrears > 0:
                extra.append(f"बक्यौता लगत रु. {arrears:,.0f} कायम (असुलीका लागि)")
            s.settled_on, s.security_released, s.arrears = day, release, arrears
            s.status = "cancelled" if s.cancelled_on else "completed"
            s.settlement_remarks = "\n".join([remarks] + extra)
            s.save()
            _log(request, s, "update", "फरफारक" + (" र जमानत फिर्ता" if release else ""))
            messages.success(request, "सम्झौता फरफारक भयो।" + (" कार्यसम्पादन जमानत फिर्ता गर्ने निर्णय भयो।" if release else ""))
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    v = lambda k, d="": p.get(k, d)  # noqa: E731
    fields = [
        F("settled_on", "फरफारक मिति", v("settled_on", to_bs(date.today())), kind="date"),
        F("settlement_remarks", "फरफारकको विवरण (क्षेत्रको अवस्था, दायित्व)", v("settlement_remarks"), kind="textarea", wide=True),
    ]
    if not s.cancelled_on:
        fields.append(F("security_released", "", v("security_released", "1" if not ms["outstanding"] else ""), kind="checkbox",
                        required=False, hint=f"कार्यसम्पादन जमानत रु. {rv.money(s.security_amount)} ({s.security_ref}) फिर्ता गर्ने"))
    if ms["penalty"]:
        fields.insert(1, F("penalty_receipt", f"जरिवाना रु. {rv.money(ms['penalty'])} असुलीको रसिद नं.", v("penalty_receipt")))
    if s.end_date and s.end_date > date.today() and not s.cancelled_on:
        fields.append(F("early_reason", "अवधि सकिनुअघि फरफारक गर्नुको कारण", v("early_reason"), kind="textarea", wide=True, required=False))
    return _render_form(request, s, {
        "title": "सम्झौता सम्पन्न र अन्तिम फरफारक", "icon": "flag-checkered", "errors": errors, "submit": "फरफारक गर्नुहोस्",
        "note": f"सम्झौता रु. {rv.money(ms['due'])} · असुल रु. {rv.money(ms['paid'])} · बाँकी रु. {rv.money(ms['outstanding'])}"
                + (f" · जरिवाना रु. {rv.money(ms['penalty'])}" if ms["penalty"] else "")
                + (f" · विलम्ब शुल्क बाँकी रु. {rv.money(ms['late_pending'])}" if ms["late_pending"] else "")
                + (" · सम्झौता रद्द भएकाले बाँकी रकम बक्यौता लगतमा राखिन्छ" if s.cancelled_on else ""),
        "sections": [{"title": "फरफारक", "icon": "flag-checkered", "fields": fields}],
    })


# ---------------------------------------------------------------- छाप्ने
@login_required
def print_doc(request, sid, doc):
    if (r := _guard(request, "rev.print")):
        return r
    s = _source(request, sid)
    need = rv.PRINT_NEEDS.get(doc)
    inst = pay = None
    if doc == "receipt":
        pay = RevenuePayment.objects.filter(instalment__source=s, id=request.GET.get("p") or 0).select_related("instalment").first()
        if pay is None:
            messages.error(request, "असुली रसिद भेटिएन।")
            return redirect(with_open(reverse("revenue_list"), s.id))
        inst = pay.instalment
    elif doc == "reminder":
        inst = s.instalments.filter(id=request.GET.get("i") or 0).first()
        if inst is None or rv.D(inst.paid_amount) >= rv.D(inst.amount):
            messages.error(request, "बाँकी किस्ता भेटिएन।")
            return redirect(with_open(reverse("revenue_list"), s.id))
    elif need is None or not need[0](s):
        messages.error(request, f"“{s.name}”: {need[1] if need else 'अमान्य कागजात।'}")
        return redirect(with_open(reverse("revenue_list"), s.id))
    RevenuePrint.objects.create(source=s, doc_type=doc, printed_by=request.user)
    return render(request, "projects/revenue_print.html", {
        "s": s, "doc": doc, "inst": inst, "pay": pay, "ranked": rv.ranked(s), "rec": rv.recommended(s), "ms": rv.money_status(s),
        "pay_total": (rv.D(pay.amount) + rv.D(pay.late_fee)) if pay else None,
        "fee": rv.late_fee(rv.D(inst.amount) - rv.D(inst.paid_amount), inst.due_date, date.today()) if doc == "reminder" else None,
        "L": rv.settings_(),
        "today": date.today(), "back": with_open(reverse("revenue_list"), s.id),
        "days": (s.bid_deadline - s.notice_date).days if s.bid_deadline and s.notice_date else None,
    })


# ---------------------------------------------------------------- पुनः बोलपत्र आह्वान
@login_required
def retender(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    ok = bool(s.notice_date and not s.award_at and ((rv.current_bids(s) and rv.recommended(s) is None) or
                                                     (not rv.current_bids(s) and s.bid_deadline and s.bid_deadline < date.today())))
    if not ok:
        messages.error(request, "मान्य बोलपत्र नआएको अवस्थामा मात्र पुनः आह्वान गर्न मिल्छ।")
        return redirect(_next(request, s))
    errors = []
    if request.method == "POST":
        f = Form(request)
        reason = f.text("reason", "पुनः आह्वानको कारण")
        new_min = f.amount("new_min_bid", "नयाँ न्यूनतम कबोल", required=False, positive=False)
        errors = f.errors
        if new_min and new_min > rv.D(s.min_bid):
            errors.append("नयाँ न्यूनतम कबोल अघिल्लोभन्दा बढी राख्न परे मूल्याङ्कन नै सच्याउनुहोस्।")
        if not errors:
            lowered = bool(new_min and new_min < rv.D(s.min_bid))
            with transaction.atomic():
                RevenueRetender.objects.create(source=s, round=s.tender_round, date=date.today(), reason=reason,
                                               old_min_bid=s.min_bid, new_min_bid=new_min or s.min_bid, created_by=request.user)
                s.bids.filter(round=s.tender_round, security_status="held").exclude(security_kind="").update(
                    security_status="returned", security_action_on=date.today())
                s.tender_round += 1
                s.notice_date = s.bid_deadline = s.opening_date = None
                if lowered:
                    s.min_bid = new_min
                    s.approved_at = None          # घटाइएको न्यूनतम कबोल पुनः स्वीकृत हुनुपर्छ
                    s.approval_remarks = f"{s.approval_remarks}\n(पुनः आह्वान {s.tender_round - 1}: न्यूनतम कबोल घटाइएको)".strip()
                s.save()
            _log(request, s, "update", f"पुनः आह्वान ({s.tender_round} औँ पटक)" + (f", न्यूनतम कबोल {new_min}" if lowered else ""))
            messages.success(request, "पुनः आह्वानका लागि तयार भयो।" + (" न्यूनतम कबोल घटाइएकाले पहिले स्वीकृत गराउनुहोस्।" if lowered
                                                                        else " अब नयाँ सूचना प्रकाशित गर्नुहोस्।"))
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    return _render_form(request, s, {
        "title": "पुनः बोलपत्र आह्वान", "icon": "rotate", "errors": errors, "submit": "पुनः आह्वान गर्नुहोस्",
        "note": f"{rv.np(s.tender_round)} औँ पटकको आह्वानमा मान्य बोलपत्र आएन। अघिल्ला बोलपत्रका जमानत फिर्ता हुन्छन्। "
                "न्यूनतम कबोल घटाउने भए फेरि प्रशासनिक स्वीकृति चाहिन्छ।",
        "sections": [{"title": "पुनः आह्वान", "icon": "rotate", "fields": [
            F("reason", "कारण (बोलपत्र नपरेको / सबै अमान्य …)", p.get("reason", ""), kind="textarea", wide=True),
            F("new_min_bid", f"नयाँ न्यूनतम कबोल (रु.) — हाल रु. {rv.money(s.min_bid)}", p.get("new_min_bid", ""), required=False,
              hint="खाली छोडे उही रहन्छ"),
        ]}],
    })


# ---------------------------------------------------------------- सम्झौता नगरेको: जमानत जफत, अर्को बोलपत्रदाता
@login_required
def default(request, sid):
    if (r := _guard(request, "rev.approve", "rev.manage")):
        return r
    s = _source(request, sid)
    if not rv.sign_overdue(s):
        messages.error(request, "स्वीकृत भएको म्याद नाघेको र सम्झौता नभएको अवस्थामा मात्र।")
        return redirect(_next(request, s))
    b = s.selected
    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip()
        if not reason:
            messages.error(request, "कारण / निर्णय लेख्नुहोस्।")
        else:
            with transaction.atomic():
                b.defaulted, b.eligible = True, False
                b.remarks = f"स्वीकृतपछि सम्झौता नगरेको — {reason}"[:250]
                if b.security_kind:
                    b.security_status, b.security_action_on = "forfeited", date.today()
                b.save()
                s.selected, s.award_at, s.award_approver = None, None, ""
                s.award_remarks = f"{b.name} ले सम्झौता नगरेकाले स्वीकृति रद्द: {reason}"
                s.save()
            _log(request, s, "update", f"{b.name} सम्झौता नगरेको — जमानत जफत")
            nxt = rv.recommended(s)
            messages.warning(request, f"{b.name} को बोलपत्र जमानत जफत भयो।" +
                             (f" अर्को मान्य बोलपत्रदाता {nxt.name} (रु. {rv.money(nxt.amount)}) स्वीकृत गर्न सकिन्छ।" if nxt
                              else " अर्को मान्य बोलपत्र छैन — पुनः आह्वान गर्नुहोस्।"))
            return redirect(_next(request, s))
    return _render_form(request, s, {
        "title": "सम्झौता नगरेको — बोलपत्र जमानत जफत", "icon": "user-xmark", "errors": [], "submit": "जफत गर्नुहोस्",
        "note": f"{b.name} ले स्वीकृत भएको {rv.np(rv.settings_().rev_sign_days)} दिनभित्र सम्झौता गरेन। बोलपत्र जमानत "
                f"{('रु. ' + rv.money(b.security_amount)) if b.security_amount else ''} {b.security_ref} जफत गरी स्वीकृति रद्द हुन्छ; "
                "त्यसपछि अर्को उच्चतम मान्य बोलपत्रदाता स्वीकृत गर्न सकिन्छ।",
        "sections": [{"title": "निर्णय", "icon": "gavel", "fields": [
            F("reason", "कारण / निर्णय नं.", request.POST.get("reason", ""), kind="textarea", wide=True)]}],
    })


# ---------------------------------------------------------------- बोलपत्र जमानत दर्ता
@login_required
def securities(request, sid=None):
    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    qs = RevenueBid.objects.exclude(security_kind="").select_related("source", "source__fiscalyear").order_by("-source_id", "-amount")
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(source__ward_id__in=wards)
    src = str(sid) if sid else request.GET.get("source", "")
    if src.isdigit():
        qs = qs.filter(source_id=src)
    st = request.GET.get("status", "")
    if st in dict(RevenueBid.SEC_STATUS):
        qs = qs.filter(security_status=st)
    if request.method == "POST":
        if "rev.manage" not in P:
            return redirect("unauthorized")
        ids = [int(x) for x in request.POST.getlist("bid") if x.isdigit()]
        n = 0
        for b in RevenueBid.objects.filter(id__in=ids, security_status="held").select_related("source"):
            s = b.source
            if wards is not None and s.ward_id not in wards:
                continue
            if b.defaulted:
                continue
            if s.selected_id == b.id and not s.agreement_date:
                continue                      # सफल बोलपत्रदाताको जमानत सम्झौतासम्म राखिन्छ
            b.security_status, b.security_action_on = "returned", date.today()
            b.save(update_fields=["security_status", "security_action_on"])
            n += 1
        messages.success(request, f"{rv.np(n)} वटा बोलपत्र जमानत फिर्ता दर्ता भयो।" if n else "फिर्ता गर्न मिल्ने जमानत छानिएन।")
        return redirect(request.get_full_path())
    today = date.today()
    rows = list(qs[:500])
    return render(request, "projects/revenue_securities.html", {
        "rows": rows, "f": {"status": st, "source": src}, "today": today, "can_manage": "rev.manage" in P,
        "total_held": sum((rv.D(b.security_amount) for b in rows if b.security_status == "held"), rv.ZERO),
        "statuses": RevenueBid.SEC_STATUS,
    })


# ---------------------------------------------------------------- सम्झौता रद्द
@login_required
def cancel(request, sid):
    if (r := _guard(request, "rev.approve")):
        return r
    s = _source(request, sid)
    if not s.agreement_date or s.settled_on or s.cancelled_on:
        messages.error(request, "चालु सम्झौता मात्र रद्द गर्न मिल्छ।")
        return redirect(_next(request, s))
    ms = rv.money_status(s)
    errors = []
    if request.method == "POST":
        f = Form(request)
        day = f.day("cancelled_on", "रद्द मिति")
        reason = f.text("cancel_reason", "रद्द गर्नुको कारण")
        ref = f.text("cancel_ref", "निर्णय नं.")
        forfeit = bool(request.POST.get("security_forfeited"))
        errors = f.errors
        if day and day < s.agreement_date:
            errors.append("रद्द मिति सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        if day and day > date.today():
            errors.append("रद्द मिति भविष्यको हुन सक्दैन।")
        if not errors:
            s.cancelled_on, s.cancel_reason, s.cancel_ref, s.security_forfeited = day, reason, ref, forfeit
            s.status = "cancelled"
            s.save()
            _log(request, s, "update", f"सम्झौता रद्द ({ref})" + (" — कार्यसम्पादन जमानत जफत" if forfeit else ""))
            messages.warning(request, "सम्झौता रद्द भयो। बाँकी किस्ता र विलम्ब शुल्क फरफारक गर्दा बक्यौता लगतमा राखिन्छ; "
                                      "बाँकी अवधिको लागि पुनः बोलपत्र गर्न सकिन्छ।")
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    return _render_form(request, s, {
        "title": "सम्झौता रद्द", "icon": "ban", "errors": errors, "submit": "सम्झौता रद्द गर्नुहोस्",
        "note": f"असुल रु. {rv.money(ms['paid'])} / {rv.money(ms['due'])} · म्याद नाघेको रु. {rv.money(ms['overdue_amount'])}"
                + (f" · जरिवाना रु. {rv.money(ms['penalty'])}" if ms["penalty"] else "")
                + " — किस्ता नबुझाएको वा शर्त गम्भीर उल्लङ्घन गरेमा मात्र।",
        "sections": [{"title": "रद्द", "icon": "ban", "fields": [
            F("cancelled_on", "रद्द मिति", p.get("cancelled_on", to_bs(date.today())), kind="date"),
            F("cancel_ref", "निर्णय नं. / मिति", p.get("cancel_ref", "")),
            F("cancel_reason", "कारण (किस्ता नबुझाएको, शर्त उल्लङ्घन …)", p.get("cancel_reason", ""), kind="textarea", wide=True),
            F("security_forfeited", "", p.get("security_forfeited", "1"), kind="checkbox", required=False,
              hint=f"कार्यसम्पादन जमानत रु. {rv.money(s.security_amount)} ({s.security_ref}) जफत गर्ने"),
        ]}],
    })


# ---------------------------------------------------------------- अर्को आ.व. / बाँकी अवधिको लागि सार्ने
@login_required
def next_year(request, sid):
    if (r := _guard(request, "rev.manage")):
        return r
    s = _source(request, sid)
    remainder = request.GET.get("mode") == "remainder" or request.POST.get("mode") == "remainder"
    if not (s.settled_on or s.cancelled_on) or s.followers.exists():
        messages.error(request, "फरफारक / रद्द भएको र अघि नसारिएको स्रोत मात्र।")
        return redirect(_next(request, s))
    fys = list(FiscalYear.objects.order_by("name"))
    later = [f for f in fys if f.name > s.fiscalyear.name]
    errors = []
    if request.method == "POST":
        fy = FiscalYear.objects.filter(id=request.POST.get("fiscalyear") or 0).first()
        if fy is None:
            errors.append("आर्थिक वर्ष छान्नुहोस्।")
        elif not remainder and fy.name <= s.fiscalyear.name:
            errors.append("अर्को (पछिको) आर्थिक वर्ष छान्नुहोस्।")
        months = request.POST.get("contract_months") or ""
        if not months.isdigit() or not (1 <= int(months) <= 60):
            errors.append("ठेक्का अवधि १ देखि ६० महिनासम्म।")
        name = (request.POST.get("name") or "").strip() or s.name
        if fy and RevenueSource.objects.filter(fiscalyear=fy, name=name).exists():
            errors.append(f"आ.व. {fy.name} मा “{name}” पहिले नै छ — नाम फरक राख्नुहोस्।")
        if not errors:
            n = RevenueSource.objects.create(
                fiscalyear=fy, name=name, category=s.category, ward=s.ward, location=s.location, boundary=s.boundary,
                unit=s.unit, contract_months=int(months), previous=s, created_by=request.user,
                description=(f"अघिल्लो: आ.व. {s.fiscalyear.name} — {s.selected.name if s.selected else ''} रु. "
                             f"{rv.money(s.contract_amount)}" + (f", रद्द {bs_date(s.cancelled_on)}" if s.cancelled_on else "")),
                # सर्वेक्षण र वातावरणीय स्वीकृति म्याद बाँकी भए सारिन्छ (नयाँ सर्वेक्षण मिति भने चाहिन्छ)
                **({k: getattr(s, k) for k in ("env_type", "env_ref", "env_approved_on", "env_valid_until", "permitted_area")}
                   if s.env_valid_until and s.env_valid_until > date.today() else {}))
            _log(request, n, "create", f"{'बाँकी अवधिको पुनः बोलपत्र' if remainder else 'अर्को आ.व.'} — #{s.id} बाट")
            messages.success(request, f"आ.व. {fy.name} को “{n.name}” बनाइयो। सर्वेक्षण र मूल्याङ्कनबाट सुरु गर्नुहोस् "
                                      f"(अघिल्लो सम्झौता रु. {rv.money(s.contract_amount)})।")
            return redirect(with_open(reverse("revenue_list"), n.id))
    p = request.POST if request.method == "POST" else {}
    remaining_months = max(1, round(((s.end_date - date.today()).days) / 30.4)) if remainder and s.end_date else s.contract_months
    default_fy = s.fiscalyear if remainder else (later[0] if later else None)
    return _render_form(request, s, {
        "title": "बाँकी अवधिको पुनः बोलपत्र" if remainder else "अर्को आ.व. का लागि सार्नुहोस्", "icon": "forward",
        "errors": errors, "submit": "बनाउनुहोस्",
        "note": "स्रोतको विवरण, सीमाना र (म्याद बाँकी भए) वातावरणीय स्वीकृति सारिन्छ; सर्वेक्षण, मूल्याङ्कन र स्वीकृति नयाँ गर्नुपर्छ। "
                f"अघिल्लो सम्झौता रु. {rv.money(s.contract_amount)} — दर तय गर्न आधार।",
        "sections": [{"title": "नयाँ रेकर्ड", "icon": "forward", "fields": [
            F("name", "नाम", p.get("name", s.name + (" (बाँकी अवधि)" if remainder else ""))),
            F("fiscalyear", "आर्थिक वर्ष", p.get("fiscalyear", str(default_fy.id) if default_fy else ""), kind="select",
              options=[(str(x.id), x.name) for x in (fys if remainder else later)]),
            F("contract_months", "ठेक्का अवधि (महिना)", p.get("contract_months", str(remaining_months))),
        ]}],
        "extra_hidden": {"mode": "remainder" if remainder else ""},
    })


# ---------------------------------------------------------------- उत्खनन परिमाण
@login_required
def extract(request, sid):
    if (r := _guard(request, "rev.survey", "rev.manage", "rev.collect")):
        return r
    s = _source(request, sid)
    if not s.agreement_date or s.settled_on or s.cancelled_on or not rv.needs_survey(s):
        messages.error(request, "चालु नदीजन्य पदार्थ ठेक्कामा मात्र।")
        return redirect(_next(request, s))
    ms = rv.money_status(s)
    limit = ms["qty_limit"]
    errors = []
    if request.method == "POST":
        f = Form(request)
        day = f.day("date", "मिति")
        qty = f.amount("quantity", "परिमाण")
        ref = f.text("ref", "चलान / अवधि", required=False)
        errors = f.errors
        if day and (day > date.today() or day < s.start_date):
            errors.append("मिति ठेक्का सुरु मितिदेखि आजसम्मको हुनुपर्छ।")
        if (e := rv.env_problem(s)) and not errors:
            errors.append(e + " — उत्खनन दर्ता गर्न मिल्दैन।")
        if qty is not None and limit and ms["extracted"] + qty > limit:
            errors.append(f"कुल {rv.money(ms['extracted'] + qty)} {s.unit} — स्वीकृत {rv.money(limit)} {s.unit} नाघ्छ। "
                          "बढी उत्खनन भएको भए अनुगमनमा उल्लङ्घन र जरिवाना दर्ता गर्नुहोस्।")
        if not errors:
            RevenueExtraction.objects.create(source=s, date=day, quantity=qty, ref=ref,
                                             remarks=(request.POST.get("remarks") or "").strip()[:250], created_by=request.user)
            total = ms["extracted"] + qty
            _log(request, s, "create", f"उत्खनन {qty} {s.unit}")
            if limit and total >= limit * Decimal("0.8"):
                messages.warning(request, f"स्वीकृत परिमाणको {rv.np(round(total * 100 / limit))}% पुग्यो।")
            messages.success(request, f"{rv.money(qty)} {s.unit} दर्ता भयो (कुल {rv.money(total)} / {rv.money(limit)})।")
            return redirect(_next(request, s))
    p = request.POST if request.method == "POST" else {}
    return _render_form(request, s, {
        "title": "उत्खनन / ढुवानी परिमाण", "icon": "truck", "errors": errors, "submit": "दर्ता गर्नुहोस्",
        "note": f"स्वीकृत (IEE/EIA अनुसार) {rv.money(limit)} {s.unit} · अहिलेसम्म {rv.money(ms['extracted'])} {s.unit}"
                + (f" ({rv.np(ms['extracted_pct'])}%)" if ms["extracted_pct"] is not None else "") + " · ८०% मा चेतावनी, १००% मा रोकिन्छ",
        "sections": [{"title": "परिमाण", "icon": "truck", "fields": [
            F("date", "मिति / अवधिको अन्तिम दिन", p.get("date", to_bs(date.today())), kind="date"),
            F("quantity", f"परिमाण ({s.unit})", p.get("quantity", "")),
            F("ref", "चलान / ढुवानी पुर्जी नं. वा अवधि", p.get("ref", ""), required=False),
            F("remarks", "कैफियत", p.get("remarks", ""), required=False),
        ]}],
    })


# ---------------------------------------------------------------- प्रतिवेदन
def _report_rows(request):
    qs, wards = _scoped(request)
    f = {k: (request.GET.get(k) or "").strip() for k in ("fiscalyear", "ward", "category", "group")}
    if f["fiscalyear"].isdigit():
        qs = qs.filter(fiscalyear_id=f["fiscalyear"])
    if f["ward"].isdigit():
        qs = qs.filter(ward_id=f["ward"])
    if f["category"] in dict(RevenueSource.CATEGORIES):
        qs = qs.filter(category=f["category"])
    rows = []
    for s in qs.order_by("fiscalyear__name", "ward__name", "name"):
        ms = rv.money_status(s)
        uplift = (round((rv.D(s.contract_amount) - rv.D(s.min_bid)) * 100 / rv.D(s.min_bid), 1)
                  if s.contract_amount and s.min_bid else None)
        rows.append({"s": s, "est": rv.D(s.est_revenue), "min_bid": rv.D(s.min_bid), "contract": rv.D(s.contract_amount),
                     "uplift": uplift, "collected": ms["paid"], "late": ms["late_paid"], "penalty": ms["penalty"],
                     "outstanding": rv.ZERO if s.settled_on else ms["outstanding"], "arrears": rv.D(s.arrears),
                     "overdue": ms["overdue_amount"] if not s.settled_on else rv.ZERO,
                     "bids": len(rv.current_bids(s)), "status": s.get_status_display()})
    keyf = {"ward": lambda r: f"वडा नं. {r['s'].ward.name}" if r["s"].ward else "पालिका",
            "category": lambda r: r["s"].get_category_display(),
            "fiscalyear": lambda r: f"आ.व. {r['s'].fiscalyear.name}"}.get(f["group"])
    cols = ("est", "min_bid", "contract", "collected", "late", "penalty", "outstanding", "overdue", "arrears")
    groups = {}
    if keyf:
        for r in rows:
            g = groups.setdefault(keyf(r), {"n": 0, **{c: rv.ZERO for c in cols}})
            g["n"] += 1
            for c in cols:
                g[c] += r[c]
    total = {"n": len(rows), **{c: sum((r[c] for r in rows), rv.ZERO) for c in cols}}
    return rows, groups, total, f, wards


@login_required
def report(request):
    if not user_perms(request.user) & VIEW:
        return redirect("unauthorized")
    rows, groups, total, f, wards = _report_rows(request)
    if request.GET.get("export") == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "राजस्व आम्दानी"
        ws.append(["क्र.सं.", "आ.व.", "वडा", "प्रकार", "राजस्व स्रोत", "ठेकेदार", "अनुमानित राजस्व", "न्यूनतम कबोल", "सम्झौता रकम",
                   "न्यूनतमभन्दा बढी %", "असुल", "विलम्ब शुल्क", "जरिवाना", "बाँकी", "म्याद नाघेको", "बक्यौता", "स्थिति"])
        for c in ws[1]:
            c.font = Font(bold=True)
        for n, r in enumerate(rows, 1):
            s = r["s"]
            ws.append([n, s.fiscalyear.name, s.ward.name if s.ward else "", s.get_category_display(), s.name,
                       s.selected.name if s.selected else "", float(r["est"]), float(r["min_bid"]), float(r["contract"]),
                       float(r["uplift"]) if r["uplift"] is not None else None, float(r["collected"]), float(r["late"]),
                       float(r["penalty"]), float(r["outstanding"]), float(r["overdue"]), float(r["arrears"]), r["status"]])
        ws.append(["", "", "", "", "जम्मा", "", *[float(total[c]) for c in ("est", "min_bid", "contract")], None,
                   *[float(total[c]) for c in ("collected", "late", "penalty", "outstanding", "overdue", "arrears")], ""])
        for col, w in zip("ABCDEFGHIJKLMNOPQ", (6, 9, 6, 22, 34, 24, 14, 14, 14, 10, 14, 12, 12, 14, 14, 12, 12)):
            ws.column_dimensions[col].width = w
        resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="revenue-report.xlsx"'
        wb.save(resp)
        return resp
    keep = request.GET.copy()
    keep.pop("export", None)
    keep.pop("print", None)
    return render(request, "projects/revenue_report_print.html" if request.GET.get("print") else "projects/revenue_report.html", {
        "rows": rows, "groups": groups, "total": total, "f": f, "qs": keep.urlencode(),
        "wards": Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all(),
        "fiscal_years": FiscalYear.objects.order_by("-name"), "categories": RevenueSource.CATEGORIES, "today": date.today(),
        "fy_name": next((x.name for x in FiscalYear.objects.filter(id=f["fiscalyear"] or 0)), ""),
    })


# ---------------------------------------------------------------- SuTRA सँग रसिद मिलान
SUTRA_HEADERS = {
    "receipt": ("receipt no", "receipt", "receipt number", "voucher no", "रसिद नं", "रसिद नं.", "रसिद नम्बर", "भौचर नं", "भौचर नं."),
    "amount": ("amount", "रकम", "जम्मा रकम", "आम्दानी रकम", "credit", "जम्मा"),
    "date": ("date", "मिति", "receipt date", "रसिद मिति"),
}


def _parse_sutra(fobj, filename):
    import csv
    import io
    import re

    from biddings.views_workflow import to_dec

    try:
        if filename.lower().endswith(".csv"):
            rows = list(csv.reader(io.StringIO(fobj.read().decode("utf-8-sig", "ignore"))))
        else:
            from openpyxl import load_workbook
            rows = [list(r) for r in load_workbook(fobj, data_only=True, read_only=True).active.iter_rows(values_only=True)]
    except Exception:
        return None, "फाइल पढ्न सकिएन — Excel (.xlsx) वा CSV मात्र।"
    col = None
    for i, r in enumerate(rows[:15]):
        names = [str(c).strip().lower().rstrip(":") if c is not None else "" for c in r]
        found = {k: names.index(n) for k, al in SUTRA_HEADERS.items() for n in names if n in al}
        if "receipt" in found and "amount" in found:
            col, rows = found, rows[i + 1:]
            break
    if col is None:
        return None, "शीर्ष पङ्क्तिमा “रसिद नं.” र “रकम” स्तम्भ चाहिन्छ।"
    out = {}
    for r in rows:
        rec = str(r[col["receipt"]] if col["receipt"] < len(r) and r[col["receipt"]] is not None else "").strip()
        if not rec:
            continue
        amt = to_dec(re.sub(r"[^\d.०-९]", "", str(r[col["amount"]] or "")))
        out[rec] = out.get(rec, rv.ZERO) + (amt if amt not in (None, "bad") else rv.ZERO)
    return out, ""


@login_required
def sutra(request):
    P = user_perms(request.user)
    if not P & {"rev.collect", "rev.manage"}:
        return redirect("unauthorized")
    fy = request.POST.get("fiscalyear") or request.GET.get("fiscalyear") or ""
    pays = RevenuePayment.objects.select_related("instalment__source__fiscalyear", "instalment__source__selected")
    wards = _user_wards(request.user)
    if wards is not None:
        pays = pays.filter(instalment__source__ward_id__in=wards)
    if fy.isdigit():
        pays = pays.filter(instalment__source__fiscalyear_id=fy)
    result = None
    if request.method == "POST" and request.FILES.get("file"):
        data, err = _parse_sutra(request.FILES["file"], request.FILES["file"].name)
        if err:
            messages.error(request, err)
        else:
            from django.utils import timezone as tz
            ours = {p.receipt_no: p for p in pays}
            matched, mismatch, missing_here, missing_sutra = [], [], [], []
            for rec, amt in data.items():
                p = ours.get(rec)
                if p is None:
                    missing_here.append((rec, amt))
                elif abs(rv.D(p.amount) + rv.D(p.late_fee) - amt) <= 1 or abs(rv.D(p.amount) - amt) <= 1:
                    matched.append(p)
                else:
                    mismatch.append((p, amt))
            missing_sutra = [p for rec, p in ours.items() if rec not in data]
            now = tz.now()
            RevenuePayment.objects.filter(id__in=[p.id for p in matched]).update(sutra_ok=True, sutra_checked_at=now)
            RevenuePayment.objects.filter(id__in=[p.id for p, _a in mismatch] + [p.id for p in missing_sutra]).update(
                sutra_ok=False, sutra_checked_at=now)
            result = {"matched": matched, "mismatch": mismatch, "missing_here": missing_here, "missing_sutra": missing_sutra}
            messages.success(request, f"मिलान: {rv.np(len(matched))} मिल्यो, {rv.np(len(mismatch))} रकम फरक, "
                                      f"{rv.np(len(missing_sutra))} SuTRA मा छैन, {rv.np(len(missing_here))} यहाँ छैन।")
    return render(request, "projects/revenue_sutra.html", {
        "result": result, "fy": fy, "fiscal_years": FiscalYear.objects.order_by("-name"),
        "counts": {"all": pays.count(), "ok": pays.filter(sutra_ok=True).count(),
                   "unchecked": pays.filter(sutra_checked_at__isnull=True).count()},
    })


# ================================================================ सार्वजनिक (लगइन नचाहिने)
def _public_ctx(request, **kw):
    from . import revenue_portal as rp

    return {"bidder": rp.current_bidder(request), "portal": rv.settings_().rev_portal, **kw}


def public_list(request):
    today = date.today()
    qs = RevenueSource.objects.filter(approved_at__isnull=False, notice_date__isnull=False, notice_date__lte=today) \
        .select_related("ward", "fiscalyear", "selected").order_by("-notice_date")
    active = [s for s in qs if s.bid_deadline and s.bid_deadline >= today and not s.award_at and not s.cancelled_on]
    closed = [s for s in qs if s.bid_deadline and s.bid_deadline < today and not s.award_at][:20]
    awarded = [s for s in qs if s.award_at][:20]
    return render(request, "projects/revenue_public.html", _public_ctx(request, active=active, closed=closed, awarded=awarded,
                                                                        today=today))


def public_notice(request, sid):
    s = get_object_or_404(RevenueSource, id=sid, approved_at__isnull=False, notice_date__isnull=False,
                          notice_date__lte=date.today())
    return render(request, "projects/revenue_print.html", {
        "s": s, "doc": "notice", "public": True, "back": reverse("revenue_public"),
        "days": (s.bid_deadline - s.notice_date).days if s.bid_deadline else None})


def portal_register(request):
    from django.contrib.auth.hashers import make_password

    from . import revenue_portal as rp
    from .models import RevenueBidder

    if not rv.settings_().rev_portal:
        return redirect("revenue_public")
    errors, p = [], request.POST if request.method == "POST" else {}
    if request.method == "POST":
        if rp.throttle(request, "register", limit=10, seconds=3600):
            errors.append("धेरै प्रयास भयो — एक घण्टापछि प्रयास गर्नुहोस्।")
        name, mobile = (p.get("name") or "").strip(), (p.get("mobile") or "").strip()
        pan, pw = (p.get("pan") or "").strip(), p.get("password") or ""
        kind = p.get("kind") if p.get("kind") in dict(RevenueBidder.KINDS) else "company"
        if not name or not (p.get("address") or "").strip():
            errors.append("नाम र ठेगाना भर्नुहोस्।")
        if not (mobile.isdigit() and len(mobile) == 10):
            errors.append("मोबाइल नम्बर १० अङ्कको हुनुपर्छ।")
        elif RevenueBidder.objects.filter(mobile=mobile).exists():
            errors.append("यो मोबाइल नम्बरबाट पहिले नै दर्ता छ — लगइन गर्नुहोस्।")
        if kind == "company" and not (pan.isdigit() and len(pan) == 9):
            errors.append("फर्म / कम्पनीको PAN ९ अङ्कको हुनुपर्छ।")
        if len(pw) < 8 or pw != p.get("password2"):
            errors.append("पासवर्ड कम्तीमा ८ अक्षरको र दुवै पटक एउटै हुनुपर्छ।")
        doc = request.FILES.get("reg_doc")
        if doc and (os.path.splitext(doc.name)[1].lower() not in {".pdf", ".jpg", ".jpeg", ".png"} or doc.size > UPLOAD_MAX):
            errors.append("दर्ता प्रमाणपत्र PDF / JPG / PNG, १० MB सम्म।")
        if not errors:
            b = RevenueBidder.objects.create(kind=kind, name=name, pan=pan, reg_no=(p.get("reg_no") or "").strip()[:100],
                                             address=p["address"].strip()[:250], mobile=mobile, email=(p.get("email") or "").strip()[:150],
                                             password=make_password(pw), reg_doc=doc)
            request.session.cycle_key()
            request.session[rp.SESSION_KEY] = b.id
            messages.success(request, "दर्ता भयो। अब खुला बोलपत्रमा भाग लिन सक्नुहुन्छ।")
            return redirect("revenue_public")
    return render(request, "projects/revenue_portal_register.html", _public_ctx(request, errors=errors, p=p))


def portal_login(request):
    from django.contrib.auth.hashers import check_password

    from . import revenue_portal as rp
    from .models import RevenueBidder

    errors = []
    if request.method == "POST":
        mobile = (request.POST.get("mobile") or "").strip()
        if rp.throttle(request, f"login:{mobile}"):
            errors.append("धेरै पटक गलत प्रयास — १५ मिनेटपछि प्रयास गर्नुहोस्।")
        else:
            b = RevenueBidder.objects.filter(mobile=mobile, is_active=True).first()
            if b and check_password(request.POST.get("password") or "", b.password):
                rp.reset_throttle(request, f"login:{mobile}")
                request.session.cycle_key()
                request.session[rp.SESSION_KEY] = b.id
                return redirect("revenue_public")
            errors.append("मोबाइल नम्बर वा पासवर्ड मिलेन।")
    return render(request, "projects/revenue_portal_login.html", _public_ctx(request, errors=errors))


def portal_logout(request):
    from . import revenue_portal as rp

    request.session.pop(rp.SESSION_KEY, None)
    return redirect("revenue_public")


def portal_bid(request, sid):
    """सिलबन्दी अनलाइन बोलपत्र पेश / म्यादभित्र परिवर्तन."""
    from django.utils import timezone as tz

    from . import revenue_portal as rp

    bidder = rp.current_bidder(request)
    if bidder is None:
        return redirect("revenue_portal_login")
    if not rv.settings_().rev_portal:
        return redirect("revenue_public")
    s = get_object_or_404(RevenueSource, id=sid)
    existing = RevenueOnlineBid.objects.filter(source=s, bidder=bidder, round=s.tender_round).first()
    if not rp.open_for_bids(s):
        messages.error(request, "यो बोलपत्र अहिले खुला छैन (पेश गर्ने म्याद सकियो वा सुरु भएको छैन)।")
        return redirect("revenue_public")
    errors = []
    if request.method == "POST":
        from biddings.views_workflow import to_dec
        amt = to_dec(request.POST.get("amount"))
        sec = to_dec(request.POST.get("security_amount"))
        if amt in (None, "bad") or amt <= 0:
            errors.append("कबोल अङ्क अङ्कमा लेख्नुहोस्।")
        elif s.min_bid and amt < rv.D(s.min_bid):
            errors.append(f"न्यूनतम कबोल रु. {rv.money(s.min_bid)} भन्दा कम मान्य हुँदैन।")
        if sec in (None, "bad") or (amt not in (None, "bad") and sec < rv.security_required(s, amt)):
            errors.append(f"बोलपत्र जमानत कबोल अङ्कको {rv.np(f'{rv.D(s.bid_security_pct):g}')}% चाहिन्छ।")
        if request.POST.get("security_kind") not in ("cash", "bank") or not (request.POST.get("security_ref") or "").strip():
            errors.append("जमानतको प्रकार र बैंक जमानत / धरौटी रसिद नं. लेख्नुहोस्।")
        files = {}
        for k in ("doc", "security_doc"):
            fobj = request.FILES.get(k)
            if fobj and (os.path.splitext(fobj.name)[1].lower() not in {".pdf", ".jpg", ".jpeg", ".png"} or fobj.size > UPLOAD_MAX):
                errors.append(f"{fobj.name}: PDF / JPG / PNG, १० MB सम्म।")
            elif fobj:
                files[k] = fobj
        if not (files.get("security_doc") or (existing and existing.security_doc)):
            errors.append("बोलपत्र जमानतको स्क्यान अपलोड गर्नुहोस्।")
        if (e := fm.blocked(fm.find(bidder.name, bidder.pan), bidder.name, bidder.pan)):
            errors.append(e)
        if not errors and not rp.open_for_bids(s):
            errors.append("पेश गर्ने म्याद सकियो।")
        if not errors:
            sealed, digest = rp.seal(amt)
            with transaction.atomic():
                o = existing or RevenueOnlineBid(source=s, bidder=bidder, round=s.tender_round)
                o.sealed, o.digest, o.submitted_at = sealed, digest, tz.now()
                o.security_kind, o.security_amount = request.POST["security_kind"], sec
                o.security_ref = request.POST["security_ref"].strip()[:200]
                for k, fobj in files.items():
                    setattr(o, k, fobj)
                o.save()
            return redirect("revenue_portal_ack", o.id)
    return render(request, "projects/revenue_portal_bid.html", _public_ctx(
        request, s=s, existing=existing, errors=errors, p=request.POST if request.method == "POST" else {},
        pct=rv.D(s.bid_security_pct)))


def portal_ack(request, oid):
    from . import revenue_portal as rp

    bidder = rp.current_bidder(request)
    o = get_object_or_404(RevenueOnlineBid.objects.select_related("source", "bidder"), id=oid)
    if bidder is None or o.bidder_id != bidder.id:
        return redirect("revenue_portal_login")
    return render(request, "projects/revenue_portal_ack.html", _public_ctx(request, o=o))


def portal_mine(request):
    from . import revenue_portal as rp

    bidder = rp.current_bidder(request)
    if bidder is None:
        return redirect("revenue_portal_login")
    bids = RevenueOnlineBid.objects.filter(bidder=bidder).select_related("source").order_by("-submitted_at")
    return render(request, "projects/revenue_portal_mine.html", _public_ctx(request, bids=bids, today=date.today()))
