"""वार्षिक खरिद योजना: योजनाअनुसार खरिद विधि छनौट (कानुनी सीमा र आधार जाँच), स्वीकृति, Excel र सीमा सेटिङ."""
from collections import OrderedDict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Ward
from accounts.permissions import has_perm, user_perms
from accounts.wards import sorted_wards

from . import procurement as pr
from .models import FiscalYear, ProcurementLimits, ProcurementPlan, Project

STATUS = OrderedDict([("none", "विधि नतोकिएको"), ("legacy", "विधि मात्र (योजना नबनेको)"),
                      ("draft", "स्वीकृत हुन बाँकी"), ("approved", "स्वीकृत")])
VIEW_PERMS = {"app.view", "app.manage", "app.approve"}


def _user_wards(user):
    from usercommittee.views_workflow import _user_wards as uw

    return uw(user)


def _money(raw):
    try:
        v = Decimal(str(raw or "").replace(",", "").strip().translate(str.maketrans("०१२३४५६७८९", "0123456789")))
    except (InvalidOperation, ValueError):
        return None
    return v


def _fy(request):
    v = request.GET.get("fiscalyear") or request.POST.get("fiscalyear") or ""
    fy = FiscalYear.objects.filter(id=v).first() if str(v).isdigit() else None
    from .fiscal import current_fy

    return fy or current_fy()   # पूर्वनिर्धारित: चालु आ.व.


def _row(p):
    plan = getattr(p, "procurement_plan", None)
    code = plan.method if plan else pr.code_of(p)
    st = plan.status if plan else ("legacy" if code else "none")
    cost = Decimal(str(plan.estimated_cost)) if plan else Decimal(str(p.budget or 0))
    return {"p": p, "plan": plan, "code": code, "method": pr.METHODS.get(code, {}).get("label", ""),
            "icon": pr.METHODS.get(code, {}).get("icon", ""), "status": st, "status_label": STATUS[st], "cost": cost,
            "nature": pr.NATURE_LABEL.get(plan.nature, "") if plan else "", "mpp": bool(plan and plan.multi_year)}


def _rows(request, fy):
    qs = (Project.objects.filter(fiscalyear=fy).select_related("ward", "procurement_type", "procurement_plan")
          .order_by("ward_id", "id"))
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    f = {k: (request.GET.get(k) or "").strip() for k in ("ward", "q", "method", "status")}
    if f["ward"].isdigit():
        qs = qs.filter(ward_id=f["ward"])
    if f["q"]:
        qs = qs.filter(Q(name__icontains=f["q"]) | Q(address__icontains=f["q"]))
    all_rows = [_row(p) for p in qs]
    rows = all_rows
    if f["method"] in pr.METHODS:
        rows = [r for r in rows if r["code"] == f["method"]]
    if f["status"] in STATUS:
        rows = [r for r in rows if r["status"] == f["status"]]
    return all_rows, rows, f, wards


@login_required
def app_list(request):
    P = user_perms(request.user)
    if not P & VIEW_PERMS:
        return redirect("unauthorized")
    fy = _fy(request)
    if request.method == "POST" and request.POST.get("action") == "approve":
        return _approve(request, fy)
    all_rows, rows, f, wards = _rows(request, fy) if fy else ([], [], {}, None)
    L = ProcurementLimits.get()
    if request.GET.get("export") == "xlsx":
        return _xlsx(fy, rows)
    total = sum((r["cost"] for r in all_rows), Decimal("0"))
    by_method = [{"code": c, **m, "count": sum(1 for r in all_rows if r["code"] == c),
                  "amount": sum((r["cost"] for r in all_rows if r["code"] == c), Decimal("0"))} for c, m in pr.METHODS.items()]
    counts = {k: sum(1 for r in all_rows if r["status"] == k) for k in STATUS}
    keep = request.GET.copy()
    keep.pop("export", None)
    return render(request, "projects/app_list.html", {
        "fy": fy, "fiscal_years": FiscalYear.objects.order_by("-name"), "rows": rows, "f": f, "L": L,
        "total": total, "by_method": by_method, "counts": counts, "statuses": STATUS.items(),
        "methods": pr.METHODS.items(), "qs": keep.urlencode(),
        "app_required": total > L.app_required_above,
        "mpp_required": total > L.mpp_required_above or any(r["mpp"] for r in all_rows),
        "all_wards": sorted_wards(Ward.objects.filter(id__in=wards) if wards is not None else None),
        "can_manage": "app.manage" in P, "can_approve": "app.approve" in P,
        "can_limits": "settings.procurement" in P,
    })


def _approve(request, fy):
    if not has_perm(request.user, "app.approve"):
        return redirect("unauthorized")
    ref = (request.POST.get("approval_ref") or "").strip()
    ids = [int(x) for x in request.POST.getlist("plan") if x.isdigit()]
    qs = ProcurementPlan.objects.filter(project__fiscalyear=fy, status="draft")
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(project__ward_id__in=wards)
    if ids:
        qs = qs.filter(id__in=ids)
    if not ref:
        messages.error(request, "स्वीकृत गर्दा निर्णय नं. / मिति लेख्नुहोस्।")
    else:
        n = qs.update(status="approved", approved_by=request.user, approved_at=timezone.now(), approval_ref=ref)
        messages.success(request, f"{n} वटा खरिद योजना स्वीकृत भयो।" if n else "स्वीकृत गर्न बाँकी खरिद योजना छैन।")
    return redirect(f"{request.path}?fiscalyear={fy.id}" if fy else request.path)


def _stay(response):
    """ReturnToNextMiddleware लाई ?next= मा नपठाउन (यही पेजमा बस्ने)."""
    response.stay_here = True
    return response


def _after_approve(request, project):
    from urllib.parse import urlparse

    nxt = request.GET.get("next") or ""
    if nxt.startswith("/") and not urlparse(nxt).netloc:
        return nxt
    code = pr.code_of(project)
    if code in pr.WORKFLOW_URL:
        from django.urls import reverse
        return reverse(pr.WORKFLOW_URL[code]) + f"?open={project.id}"
    if code in ("direct", "amanat", "sanstha"):
        return f"/Projects/Minor/{project.id}/"
    return f"/Projects/APP/?fiscalyear={project.fiscalyear_id}"


@login_required
def app_plan(request, project_id):
    from biddings.views_workflow import to_ad, to_bs

    P = user_perms(request.user)
    if not P & VIEW_PERMS:
        return redirect("unauthorized")
    project = get_object_or_404(Project.objects.select_related("ward", "fiscalyear", "procurement_type"), id=project_id)
    wards = _user_wards(request.user)
    if wards is not None and project.ward_id not in wards:
        return redirect("unauthorized")
    plan = getattr(project, "procurement_plan", None)
    L = ProcurementLimits.get()
    lock = pr.started(project)
    can_edit = "app.manage" in P
    data = request.POST if request.method == "POST" else request.GET
    nature = data.get("nature") or (plan.nature if plan else "works")
    cost = _money(data.get("estimated_cost")) if data.get("estimated_cost") else (
        Decimal(str(plan.estimated_cost)) if plan else Decimal(str(project.budget or 0)))
    method = data.get("method") or (plan.method if plan else pr.code_of(project))
    errors = []
    if request.method == "POST" and data.get("action") == "approve":
        if "app.approve" not in P:
            return redirect("unauthorized")
        ref = (data.get("approval_ref") or "").strip()
        if plan is None or plan.status != "draft":
            messages.error(request, "स्वीकृत गर्न बाँकी खरिद योजना छैन।")
        elif not ref:
            messages.error(request, "स्वीकृत गर्दा निर्णय नं. / मिति लेख्नुहोस्।")
        else:
            plan.status, plan.approved_by, plan.approved_at, plan.approval_ref = "approved", request.user, timezone.now(), ref
            plan.save(update_fields=["status", "approved_by", "approved_at", "approval_ref"])
            messages.success(request, f"“{project.name}” को खरिद योजना स्वीकृत भयो — अब खरिद प्रक्रिया सुरु गर्न सकिन्छ।")
            return redirect(_after_approve(request, project))
        return _stay(redirect(request.get_full_path()))
    if request.method == "POST":
        if not can_edit:
            return redirect("unauthorized")
        grounds = data.getlist("grounds")
        if lock and method != pr.code_of(project):
            errors.append(f"{lock} — अब खरिद विधि बदल्न मिल्दैन।")
        if cost is None or cost <= 0:
            errors.append("अनुमानित लागत ० भन्दा बढी अङ्कमा लेख्नुहोस्।")
        elif project.budget and cost > Decimal(str(project.budget)) + 1 and method == "uc":
            errors.append(f"अनुमानित लागत विनियोजित बजेट {pr.rs(project.budget)} भन्दा बढी छ — उपभोक्ता समिति मार्फत एउटै "
                          "आ.व. को काम मात्र हुन्छ (बहुवर्षीय हुँदैन), बजेट थप / रकमान्तर गर्नुहोस्।")
        elif project.budget and cost > Decimal(str(project.budget)) + 1 and not data.get("multi_year"):
            errors.append(f"अनुमानित लागत विनियोजित बजेट {pr.rs(project.budget)} भन्दा बढी छ — बहुवर्षीय भए “बहुवर्षीय” छान्नुहोस्, "
                          "नत्र बजेट थप / रकमान्तर गर्नुहोस्।")
        if cost:
            errors += pr.check(nature, method, cost, grounds, L)
        dates = {}
        for k in ("estimate_date", "notice_date", "contract_date", "completion_date"):
            raw = data.get(k)
            dates[k] = to_ad(raw) if raw else None
            if raw and dates[k] is None:
                errors.append("मिति मिलेन (वि.सं. YYYY-MM-DD)।")
        seq = [dates[k] for k in ("estimate_date", "notice_date", "contract_date", "completion_date") if dates[k]]
        if seq != sorted(seq):
            errors.append("समयतालिका क्रममा हुनुपर्छ: लागत अनुमान → सूचना → सम्झौता → सम्पन्न।")
        if not errors:
            with transaction.atomic():
                obj = plan or ProcurementPlan(project=project, created_by=request.user)
                changed = plan is not None and (plan.method != method or Decimal(str(plan.estimated_cost)) != cost
                                                or plan.nature != nature)
                obj.nature, obj.method, obj.estimated_cost = nature, method, cost
                obj.multi_year = bool(data.get("multi_year")) and method != "uc"   # उपभोक्ता समिति: बहुवर्षीय हुँदैन
                obj.grounds = [g for g in grounds if g in {k for k, _ in pr.GROUNDS.get(method, [])}]
                obj.justification = (data.get("justification") or "").strip()
                for k, v in dates.items():
                    setattr(obj, k, v)
                if plan is None or changed:
                    obj.status, obj.approved_by, obj.approved_at, obj.approval_ref = "draft", None, None, ""
                obj.save()
                pt = pr.type_for(method)
                if pt and project.procurement_type_id != pt.id:
                    project.procurement_type = pt
                    project.save(update_fields=["procurement_type"])
            msg = f"“{project.name}” को खरिद विधि: {pr.METHODS[method]['label']}।"
            if plan is not None and changed and plan.status == "approved":
                msg += " विधि/लागत बदलिएकाले फेरि स्वीकृत गर्नुपर्छ।"
            messages.success(request, msg)
            obj.refresh_from_db()
            if obj.status == "draft":
                if "app.approve" in P:
                    # स्वीकृत गर्ने अधिकार भए यही पेजमा बसेर स्वीकृत गर्ने (कार्यप्रवाहमा फर्काउनुअघि)
                    messages.info(request, "खरिद योजना तयार भयो — तल “स्वीकृत गर्नुहोस्” थिचेपछि मात्र खरिद प्रक्रिया सुरु हुन्छ।")
                    return _stay(redirect(request.get_full_path()))
                messages.warning(request, "खरिद योजना स्वीकृतिका लागि पेश भयो — स्वीकृत गर्ने अधिकारी (प्रमुख प्रशासकीय अधिकृत) ले "
                                          "स्वीकृत गरेपछि मात्र खरिद प्रक्रिया सुरु हुन्छ।")
            return redirect(f"/Projects/APP/?fiscalyear={project.fiscalyear_id}")
    cards = pr.evaluate(nature, cost or 0, L)
    sel_grounds = data.getlist("grounds") if request.method == "POST" else (plan.grounds if plan else [])
    g = lambda k: data.get(k) if data.get(k) is not None else (to_bs(getattr(plan, k)) if plan and getattr(plan, k) else "")  # noqa: E731
    return render(request, "projects/app_plan.html", {
        "project": project, "plan": plan, "L": L, "lock": lock, "can_edit": can_edit, "errors": errors,
        "nature": nature, "natures": pr.NATURE_LABEL.items(), "cost": cost, "method": method, "cards": cards,
        "sel_grounds": sel_grounds, "multi_year": bool(data.get("multi_year")) if request.method == "POST" else bool(plan and plan.multi_year),
        "justification": data.get("justification", plan.justification if plan else ""),
        "dates": [(k, lbl, g(k)) for k, lbl in (("estimate_date", "लागत अनुमान स्वीकृत"), ("notice_date", "सूचना / आह्वान"),
                                                 ("contract_date", "सम्झौता"), ("completion_date", "काम सम्पन्न"))],
        "workflow_url": pr.WORKFLOW_URL.get(method),
        "can_approve": "app.approve" in P,
        "plan_method_label": pr.METHODS.get(plan.method, {}).get("label", "") if plan else "",
    })


@login_required
def app_limits(request):
    if not has_perm(request.user, "settings.procurement"):
        return redirect("unauthorized")
    L = ProcurementLimits.get()
    fields = ["direct_limit", "consult_direct_limit", "quot_limit", "uc_limit", "sanstha_notice_limit",
              "app_required_above", "mpp_required_above"]
    contract_fields = [("ld_rate_per_day", "%"), ("ld_max_pct", "%"), ("variation_office_pct", "%"),
                       ("extension_notice_days", "दिन"), ("max_running_contracts", "वटा")]
    if request.method == "POST":
        vals, bad = {}, []
        for k in fields:
            v = _money(request.POST.get(k))
            if v is None or v < 0:
                bad.append(ProcurementLimits._meta.get_field(k).verbose_name)
            vals[k] = v
        for k, _u in contract_fields:
            if request.POST.get(k) is None:          # पुरानो फारम — हालकै मान राख्ने
                vals[k] = getattr(L, k)
                continue
            v = _money(request.POST.get(k))
            if v is None or v < 0 or (k != "extension_notice_days" and v > 100):
                bad.append(ProcurementLimits._meta.get_field(k).verbose_name)
            vals[k] = int(v) if v is not None and k in ("extension_notice_days", "max_running_contracts") else v
        if not bad and vals["direct_limit"] > vals["quot_limit"]:
            bad.append("सोझै खरिद सीमा दरभाउपत्र सीमाभन्दा बढी हुन मिल्दैन")
        if bad:
            messages.error(request, "मिलेन: " + ", ".join(str(b) for b in bad))
        else:
            for k, v in vals.items():
                setattr(L, k, v)
            L.note = (request.POST.get("note") or "").strip()
            if "contingency_uc" in request.POST:
                from biddings.views_workflow import to_dec
                for k in ("contingency_uc", "contingency_bid", "contingency_quot"):
                    v = to_dec(request.POST.get(k))
                    if v not in (None, "bad") and 0 <= v <= 20:
                        setattr(L, k, v)
                    else:
                        messages.warning(request, f"{ProcurementLimits._meta.get_field(k).verbose_name}: ० देखि २० सम्म मात्र — पुरानै दर राखियो।")
            L.require_approved_plan = bool(request.POST.get("require_approved_plan"))
            if "rev_late_fee_pct" in request.POST:
                from biddings.views_workflow import to_dec
                fee = to_dec(request.POST.get("rev_late_fee_pct"))
                if fee not in (None, "bad") and 0 <= fee <= 10:
                    L.rev_late_fee_pct = fee
                for k in ("rev_reminder_days", "rev_sign_days"):
                    v = (request.POST.get(k) or "").strip()
                    if v.isdigit() and 1 <= int(v) <= 90:
                        setattr(L, k, int(v))
                L.rev_portal = bool(request.POST.get("rev_portal"))
            if "field_max_distance" in request.POST:
                L.citizen_portal = bool(request.POST.get("citizen_portal"))
                v = (request.POST.get("field_max_distance") or "").strip()
                if v.isdigit() and 50 <= int(v) <= 50000:
                    L.field_max_distance = int(v)
            if "ird_page_url" in request.POST:
                L.ird_lookup_enabled = bool(request.POST.get("ird_lookup_enabled"))
                for k in ("ird_page_url", "ird_api_url"):
                    v = (request.POST.get(k) or "").strip()
                    if v.startswith("https://") or v.startswith("http://"):
                        setattr(L, k, v[:250])
            L.save()
            pr.forget_limits()
            messages.success(request, "खरिद विधिका सीमा सुरक्षित भयो।")
            return redirect("app_limits")
    return render(request, "projects/app_limits.html", {
        "L": L, "fields": [(k, ProcurementLimits._meta.get_field(k).verbose_name, getattr(L, k)) for k in fields],
        "contract_fields": [(k, ProcurementLimits._meta.get_field(k).verbose_name, getattr(L, k), u)
                            for k, u in contract_fields],
        "contingency_fields": [(k, lbl, getattr(L, k)) for k, lbl in (
            ("contingency_uc", "उपभोक्ता समिति"), ("contingency_bid", "बोलपत्र ठेक्का"), ("contingency_quot", "दरभाउपत्र खरिद"))]})


def _xlsx(fy, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    from usercommittee.workflow import bs_date

    wb = Workbook()
    ws = wb.active
    ws.title = "वार्षिक खरिद योजना"
    ws.append([f"वार्षिक खरिद योजना — आ.व. {fy.name if fy else ''}"])
    head = ["क्र.सं.", "योजनाको नाम", "वडा", "खरिदको प्रकृति", "खरिद विधि", "विनियोजित बजेट", "अनुमानित लागत", "बहुवर्षीय",
            "लागत अनुमान स्वीकृत", "सूचना / आह्वान", "सम्झौता", "काम सम्पन्न", "स्थिति", "स्वीकृत निर्णय"]
    ws.append(head)
    for c in ws[2]:
        c.font, c.fill = Font(bold=True), PatternFill("solid", fgColor="E8EEFB")
    ws["A1"].font = Font(bold=True, size=13)
    for i, r in enumerate(rows, start=1):
        pl = r["plan"]
        ws.append([i, r["p"].name, getattr(r["p"].ward, "name", ""), r["nature"], r["method"], float(r["p"].budget or 0),
                   float(r["cost"]), "हो" if r["mpp"] else "", *(bs_date(getattr(pl, k)) if pl else "" for k in
                   ("estimate_date", "notice_date", "contract_date", "completion_date")),
                   r["status_label"], pl.approval_ref if pl else ""])
    for n, w in enumerate([6, 40, 6, 14, 24, 15, 15, 9, 14, 14, 12, 12, 20, 20], start=1):
        ws.column_dimensions[ws.cell(row=2, column=n).column_letter].width = w
    ws.freeze_panes = "A3"
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="annual-procurement-plan.xlsx"'
    wb.save(resp)
    return resp
