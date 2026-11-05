"""मुख्य ड्यासबोर्ड र आर्थिक वर्ष बन्द."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.permissions import has_perm, user_perms

from . import dashboard as db
from . import yearend as ye
from .models import FiscalYear, YearEndLine


def _user_wards(user):
    from usercommittee.views_workflow import _user_wards as uw

    return uw(user)


def _fy(request):
    fys = list(FiscalYear.objects.order_by("-name"))
    sel = request.GET.get("fiscalyear") or request.POST.get("fiscalyear") or ""
    fy = next((f for f in fys if str(f.id) == sel), None)
    if fy is None:                       # पूर्वनिर्धारित: चालु आ.व.
        from .fiscal import current_fy

        fy = current_fy()
    return fy, fys


@login_required
def dashboard(request):
    P = user_perms(request.user)
    if "dashboard.view" not in P:
        return redirect("unauthorized")
    fy, fys = _fy(request)
    wards = _user_wards(request.user)
    data = db.compute(fy, wards)
    from accounts.mywork import my_work

    work = my_work(request.user)
    attention = [i for i in work["items"] if i["tone"] in ("urgent", "warn")][:10]
    return render(request, "projects/dashboard.html", {
        "fy": fy, "fiscal_years": fys, "d": data, "attention": attention, "work_total": work["total"],
        "can_close": "yearend.close" in P, "scoped": wards is not None,
        "latest_ucs": _latest_ucs(fy, wards),
        "guarantees": _guarantees_soon(wards) if P & {"bid.view", "quot.view"} else None,
        "trend": data.get("trend"),
        "chart": {"labels": [f"वडा {w['name']}" if w["name"] != "पालिका" else "पालिका" for w in data["wards"]],
                  "allocated": [float(w["allocated"]) for w in data["wards"]],
                  "spent": [float(w["spent"]) for w in data["wards"]]},
    })


def _guarantees_soon(wards, n=5):
    """म्याद सकिन नजिक ५ बैंक ग्यारेन्टी (कार्यसम्पादन र अग्रिम, फिर्ता / समायोजन भएका बाहेक) — सबै आ.व. का."""
    from django.urls import reverse

    from .views_guarantees import apg_rows, pg_rows

    rows = [dict(r, which="pg") for r in pg_rows()] + [dict(r, which="apg") for r in apg_rows()]
    rows = [r for r in rows if r["status"] != "closed" and r["expiry"]]
    if wards is not None:
        rows = [r for r in rows if r["p"].ward_id in wards]
    soon = sorted((r for r in rows if r["days"] >= 0), key=lambda r: r["days"])[:n]
    for r in soon:
        page = reverse("performance_guarantees" if r["which"] == "pg" else "advance_guarantees")
        r["url"] = f"{page}?q={r['number'] or ''}&status="
    expired = [r for r in rows if r["days"] < 0]
    return {"rows": soon, "expired": len(expired),
            "expired_url": reverse("performance_guarantees") + "?status=expired",
            "pg_url": reverse("performance_guarantees"), "apg_url": reverse("advance_guarantees")}


def _latest_ucs(fy, wards):
    """हालै दर्ता भएका ५ उपभोक्ता समिति (यो आ.व.)."""
    from usercommittee.models import UserCommittee

    qs = UserCommittee.objects.select_related("project", "project__ward", "project__cost_estimate")
    if fy:
        qs = qs.filter(project__fiscalyear=fy)
    if wards is not None:
        qs = qs.filter(project__ward_id__in=wards)
    return list(qs.order_by("-id")[:5])


@login_required
def yearend(request):
    if not has_perm(request.user, "yearend.close"):
        return redirect("unauthorized")
    fy, fys = _fy(request)
    if fy is None:
        messages.error(request, "आर्थिक वर्ष दर्ता छैन।")
        return redirect("dashboard")
    if fy.closed_at:
        return redirect("yearend_report", fy.id)
    later = [f for f in fys if f.name > fy.name]
    rows = ye.preview(fy)
    errors = []
    if request.method == "POST":
        from biddings.views_workflow import to_dec

        to_fy = FiscalYear.objects.filter(id=request.POST.get("to_fiscalyear") or 0).first()
        new_name = (request.POST.get("new_fy") or "").strip()
        ref = (request.POST.get("close_ref") or "").strip()
        if to_fy is None and new_name:
            import re
            if not re.fullmatch(r"\d{4}/\d{2}", new_name.translate(str.maketrans("०१२३४५६७८९", "0123456789"))):
                errors.append("नयाँ आ.व. को नाम २०८३/८४ जस्तो लेख्नुहोस्।")
            elif new_name <= fy.name:
                errors.append("नयाँ आ.व. बन्द गर्न लागेको आ.व. भन्दा पछिको हुनुपर्छ।")
        elif to_fy is not None and to_fy.name <= fy.name:
            errors.append("क्रमागत योजना सार्ने आ.व. पछिको हुनुपर्छ।")
        if not ref:
            errors.append("आ.व. बन्द गर्ने निर्णय नं. / मिति लेख्नुहोस्।")
        if request.POST.get("confirm") != "1":
            errors.append("“आ.व. बन्द भएपछि भुक्तानी गर्न मिल्दैन” भन्ने पुष्टि गर्नुहोस्।")
        decisions = {}
        for r in rows:
            pid = r["p"].id
            action = request.POST.get(f"action_{pid}") or r["default"]
            if action not in ("completed", "carried", "frozen"):
                action = r["default"]
            alloc = to_dec(request.POST.get(f"alloc_{pid}"))
            if action == "carried":
                if alloc in (None, "bad") or alloc < 0:
                    errors.append(f"“{r['p'].name}”: नयाँ आ.व. को आवंटन अङ्कमा लेख्नुहोस्।")
                    continue
                if r["committed"] and r["spent"] + alloc < r["committed"] - 1:
                    errors.append(f"“{r['p'].name}”: सम्झौता / लागत अनुमान रु. {r['committed']:,.0f} भएकाले खर्च + नयाँ आवंटन "
                                  f"कम्तीमा रु. {r['committed'] - r['spent']:,.0f} चाहिन्छ।")
            decisions[pid] = (action, alloc if action == "carried" else Decimal("0"))
        if any(a == "carried" for a, _x in decisions.values()) and to_fy is None and not new_name:
            errors.append("क्रमागत योजना सार्ने आ.व. छान्नुहोस् वा नयाँ आ.व. को नाम लेख्नुहोस्।")
        if not errors:
            if to_fy is None and new_name:
                to_fy = FiscalYear.objects.filter(name=new_name).first() or FiscalYear.objects.create(name=new_name)
            counts = ye.close(fy, to_fy, decisions, request.user, ref)
            from usercommittee.models import ActivityLog
            ActivityLog.objects.create(user=request.user, action="update", model_name="आर्थिक वर्ष", object_id=fy.id,
                                       object_repr=f"आ.व. {fy.name} बन्द", note=f"{ref} · क्रमागत {counts['carried']}, "
                                                                                  f"रोक्का {counts['frozen']}, सम्पन्न {counts['completed']}")
            messages.success(request, f"आ.व. {fy.name} बन्द भयो — {counts['carried']} योजना क्रमागत रूपमा "
                                      f"{to_fy.name if to_fy else ''} मा सारियो, {counts['frozen']} रोक्का, {counts['completed']} सम्पन्न।")
            return redirect("yearend_report", fy.id)
    p = request.POST if request.method == "POST" else {}
    for r in rows:
        pid = r["p"].id
        r["action"] = p.get(f"action_{pid}", r["default"])
        need = max(r["remaining"], r["committed"] - r["spent"], Decimal("0"))   # प्रतिबद्धता पुग्ने गरी सुझाव
        r["alloc"] = p.get(f"alloc_{pid}", f"{need:.0f}")
    totals = {k: sum((r[k] for r in rows), Decimal("0")) for k in ("allocated", "spent", "remaining", "retention")}
    return render(request, "projects/yearend.html", {
        "fy": fy, "fiscal_years": fys, "later": later, "rows": rows, "errors": errors, "p": p, "totals": totals,
        "suggest_new": _next_name(fy.name) if not later else "",
        "counts": {k: sum(1 for r in rows if r["default"] == k) for k in ("carried", "frozen", "completed")},
    })


def _next_name(name):
    try:
        a, b = name.split("/")
        a = int(a.translate(str.maketrans("०१२३४५६७८९", "0123456789")))
        return f"{a + 1}/{str(a + 2)[-2:]}"
    except Exception:
        return ""


@login_required
def yearend_report(request, fy_id):
    if not user_perms(request.user) & {"yearend.close", "dashboard.view"}:
        return redirect("unauthorized")
    fy = get_object_or_404(FiscalYear, id=fy_id)
    lines = list(YearEndLine.objects.filter(fiscalyear=fy).select_related("to_fiscalyear"))
    groups = []
    for key, label in YearEndLine.ACTIONS:
        xs = [x for x in lines if x.action == key]
        if xs:
            groups.append({"key": key, "label": label, "lines": xs,
                           **{k: sum((getattr(x, k) for x in xs), Decimal("0"))
                              for k in ("allocated", "spent", "committed", "new_allocation", "retention_held")}})
    total = {k: sum((getattr(x, k) for x in lines), Decimal("0")) for k in ("allocated", "spent", "new_allocation", "retention_held")}
    from .models import RevenueSource
    from . import revenue as rv
    rev = [(s, rv.money_status(s)) for s in rv.queryset().filter(fiscalyear=fy)]
    rev_out = [(s, ms) for s, ms in rev if (not s.settled_on and ms["outstanding"] > 0) or s.arrears]
    template = "projects/yearend_print.html" if request.GET.get("print") else "projects/yearend_report.html"
    return render(request, template, {
        "fy": fy, "groups": groups, "total": total, "n": len(lines), "rev_out": rev_out,
        "can_reopen": has_perm(request.user, "yearend.close") and fy.closed_at,
    })


@login_required
def yearend_reopen(request, fy_id):
    """लक मात्र खोल्ने (सारिएका क्रमागत योजना फर्किँदैनन्)."""
    if not has_perm(request.user, "yearend.close") or request.method != "POST":
        return redirect("unauthorized")
    fy = get_object_or_404(FiscalYear, id=fy_id)
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "लक खोल्नुको कारण लेख्नुहोस्।")
        return redirect("yearend_report", fy.id)
    fy.closed_at = None
    fy.close_ref = f"{fy.close_ref} | लक खोलियो: {reason}"[:200]
    fy.save(update_fields=["closed_at", "close_ref"])
    from usercommittee.models import ActivityLog
    ActivityLog.objects.create(user=request.user, action="update", model_name="आर्थिक वर्ष", object_id=fy.id,
                               object_repr=f"आ.व. {fy.name} लक खोलियो", note=reason[:250])
    messages.warning(request, f"आ.व. {fy.name} को लक खोलियो — भुक्तानी फेरि गर्न सकिन्छ। सारिएका क्रमागत योजना नयाँ आ.व. मै रहन्छन्।")
    return redirect("yearend_report", fy.id)


# ---------------------------------------------------------------- लेखापरीक्षण प्याकेट
@login_required
def audit_pack(request):
    if not has_perm(request.user, "report.uc"):
        return redirect("unauthorized")
    fy, fys = _fy(request)
    if request.GET.get("download") and fy is not None:
        from django.http import HttpResponse

        from . import auditpack

        wb = auditpack.build(fy, _user_wards(request.user))
        resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="audit-pack-{fy.name.replace("/", "-")}.xlsx"'
        wb.save(resp)
        from usercommittee.models import ActivityLog
        ActivityLog.objects.create(user=request.user, action="update", model_name="लेखापरीक्षण प्याकेट", object_id=fy.id,
                                   object_repr=f"आ.व. {fy.name} डाउनलोड", note="")
        return resp
    from . import auditpack
    start, end = auditpack.fy_range(fy) if fy else (None, None)
    return render(request, "projects/audit_pack.html", {"fy": fy, "fiscal_years": fys, "start": start, "end": end,
                                                         "scoped": _user_wards(request.user) is not None})


# ---------------------------------------------------------------- ब्याकअप
@login_required
def backups(request):
    if not has_perm(request.user, "backup.manage"):
        return redirect("unauthorized")
    from django.db import connection
    from django.http import FileResponse

    from . import backup

    schema = connection.schema_name
    if request.GET.get("file"):
        path = backup.safe_path(schema, request.GET["file"])
        if path is None:
            messages.error(request, "फाइल भेटिएन।")
            return redirect("backups")
        from usercommittee.models import ActivityLog
        ActivityLog.objects.create(user=request.user, action="update", model_name="ब्याकअप", object_repr=path.name[:250],
                                   note="डाउनलोड")
        return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name)
    if request.method == "POST":
        try:
            path, c = backup.make_backup(schema)
            from usercommittee.models import ActivityLog
            ActivityLog.objects.create(user=request.user, action="create", model_name="ब्याकअप", object_repr=path.name[:250],
                                       note=f"{c['objects']} रेकर्ड, {c['files']} फाइल")
            messages.success(request, f"ब्याकअप तयार भयो: {path.name} — {c['projects']} योजना, {c['objects']} रेकर्ड, {c['files']} फाइल।")
        except Exception as e:
            messages.error(request, f"ब्याकअप असफल: {e}")
        return redirect("backups")
    return render(request, "projects/backups.html", {"items": backup.list_backups(schema), "keep": backup.keep(),
                                                      "age": backup.latest_age_hours(schema), "schema": schema})


# ---------------------------------------------------------------- SMS / इमेल सूचना
@login_required
def alerts(request):
    if not has_perm(request.user, "alerts.manage"):
        return redirect("unauthorized")
    from django.core.paginator import Paginator

    from . import notify as nt
    from .models import NotificationLog, NotifySettings

    S = NotifySettings.get()
    errors = []
    if request.method == "POST":
        act = request.POST.get("act", "save")
        from usercommittee.models import ActivityLog
        if act == "save":
            g = request.POST.get
            S.site_url = (g("site_url") or "").strip()[:200]
            if S.site_url and not S.site_url.startswith(("https://", "http://")):
                errors.append("प्रणालीको ठेगाना https:// बाट सुरु हुनुपर्छ।")
            S.email_on = bool(g("email_on"))
            S.smtp_host = (g("smtp_host") or "").strip()[:150]
            port = (g("smtp_port") or "").strip()
            S.smtp_port = int(port) if port.isdigit() and 0 < int(port) < 65536 else 587
            S.smtp_user = (g("smtp_user") or "").strip()[:150]
            if (g("smtp_password") or "").strip():           # खाली छाडे पुरानै रहन्छ
                S.smtp_password = g("smtp_password").strip()[:200]
            S.smtp_tls = bool(g("smtp_tls"))
            S.from_email = (g("from_email") or "").strip()[:150]
            if S.email_on and not (S.smtp_host and (S.from_email or S.smtp_user)):
                errors.append("इमेल पठाउन SMTP सर्भर र पठाउने इमेल चाहिन्छ।")
            prov = g("sms_provider") or ""
            S.sms_provider = prov if prov in dict(NotifySettings.PROVIDERS) else ""
            if (g("sms_token") or "").strip():
                S.sms_token = g("sms_token").strip()[:200]
            S.sms_from = (g("sms_from") or "").strip()[:30]
            if S.sms_provider and not S.sms_token:
                errors.append("SMS का लागि API token राख्नुहोस्।")
            S.staff_digest = bool(g("staff_digest"))
            S.staff_roles = ",".join(r for r in request.POST.getlist("staff_roles") if r.isdigit())
            S.staff_sms_urgent = bool(g("staff_sms_urgent"))
            S.rev_due_sms = bool(g("rev_due_sms"))
            S.rev_late_sms = bool(g("rev_late_sms"))
            if not errors:
                S.save()
                ActivityLog.objects.create(user=request.user, action="update", model_name="SMS / इमेल सेटिङ", object_id=S.id,
                                           object_repr="सेटिङ", note=f"इमेल {'खुला' if S.email_on else 'बन्द'}, SMS {S.sms_provider or 'बन्द'}")
                messages.success(request, "सूचना सेटिङ सुरक्षित भयो।")
                return redirect("alerts")
        elif act == "clear_secret":
            which = request.POST.get("which")
            if which == "smtp":
                S.smtp_password = ""
            elif which == "sms":
                S.sms_token = ""
            S.save()
            messages.info(request, "गोप्य मान हटाइयो।")
            return redirect("alerts")
        elif act == "test":
            to = (request.POST.get("to") or "").strip()
            msg = f"{nt.palika_name()} PMS: परीक्षण सूचना — सेटिङ ठीक छ।"
            if "@" in to:
                if not nt.email_ok(to):
                    messages.error(request, "इमेल ठेगाना मिलेन।")
                    return redirect("alerts")
                ok, err = nt.send_email(S, to, "परीक्षण इमेल", msg)
                ch = "email"
            else:
                to = nt.phone(to)
                if not to:
                    messages.error(request, "मोबाइल नम्बर (९८/९७/९६ बाट सुरु हुने १० अङ्क) वा इमेल लेख्नुहोस्।")
                    return redirect("alerts")
                ok, err = nt.send_sms(S, to, msg)
                ch = "sms"
            NotificationLog.objects.create(key=f"test:{timezone_now_key()}", channel=ch, to=to, name=(request.user.get_full_name() or request.user.mobile)[:200],
                                           kind="test", body=msg, status="sent" if ok else "failed", error=err[:300])
            (messages.success if ok else messages.error)(request, f"परीक्षण {'पठाइयो' if ok else 'असफल'}: {to}" + (f" — {err}" if err else ""))
            return redirect("alerts")
        elif act in ("run", "dry"):
            c = nt.run(dry=act == "dry")
            ActivityLog.objects.create(user=request.user, action="update", model_name="SMS / इमेल सूचना", object_repr=act,
                                       note=str(c)[:250])
            if act == "dry":
                messages.info(request, f"अहिले चलाए: {c['dry']} सूचना पठाइने, {c['dup']} पहिले नै पठाइसकेको, "
                                       f"{c['no_contact']} जनाको मोबाइल / इमेल छैन।")
            else:
                (messages.success if not c["failed"] else messages.warning)(
                    request, f"{c['sent']} पठाइयो, {c['failed']} असफल, {c['dup']} पहिले नै पठाइसकेको, {c['no_contact']} सम्पर्क नभएको।")
            return redirect("alerts")
    logs = NotificationLog.objects.all()
    f = {k: request.GET.get(k, "") for k in ("status", "channel", "kind")}
    for k, v in f.items():
        if v:
            logs = logs.filter(**{k: v})
    page = Paginator(logs, 50).get_page(request.GET.get("page"))
    roles = [("2", "प्रमुख प्रशासकीय अधिकृत"), ("3", "योजना अधिकृत"), ("4", "इन्जिनियर"), ("5", "वडा कर्मचारी"), ("6", "वडा सचिव"),
             ("7", "वडा इन्जिनियर"), ("8", "पालिका इन्जिनियर"), ("9", "वडा अध्यक्ष"), ("10", "लेखा अधिकृत")]
    from collections import Counter
    from datetime import timedelta
    from django.utils import timezone as tz
    since = tz.now() - timedelta(days=30)
    stats = Counter(NotificationLog.objects.filter(created_at__gte=since).values_list("status", flat=True))
    return render(request, "projects/alerts.html", {
        "S": S, "errors": errors, "page": page, "f": f, "roles": roles, "sel_roles": (S.staff_roles or "").split(","),
        "stats": stats, "site": nt.site_url(S), "KINDS": {"staff": "कर्मचारी सारांश", "rev_due": "राजस्व किस्ता सम्झना",
                                                          "rev_late": "राजस्व किस्ता ताकेता", "test": "परीक्षण"},
    })


def timezone_now_key():
    from django.utils import timezone as tz

    return tz.now().strftime("%Y%m%d%H%M%S%f")


# ---------------------------------------------------------------- प्रतिवेदनहरू (सबै प्रतिवेदन एकै ठाउँमा)
@login_required
def reports_hub(request):
    from . import reports_hub as rh
    from .fiscal import current_fy

    fys = list(FiscalYear.objects.order_by("-name"))
    sel = request.GET.get("fiscalyear", "")
    fy = next((f for f in fys if str(f.id) == sel), None) or current_fy()
    sections = rh.build(request.user, fy)
    if not sections:
        return redirect("unauthorized")
    stars = [it for s in sections for it in s["items"] if it["star"]]
    return render(request, "projects/reports_hub.html", {
        "sections": sections, "stars": stars[:4], "fy": fy, "fiscal_years": fys,
        "total": sum(len(s["items"]) for s in sections),
    })


# ---------------------------------------------------------------- भूमिकाअनुसार गृहपृष्ठ (CAO, योजना अधिकृत)
def _role_ctx(request):
    from accounts.mywork import my_work

    from . import dashboard as db

    fy, fys = _fy(request)
    wards = _user_wards(request.user)
    d = db.compute(fy, wards)
    P = user_perms(request.user)
    work = my_work(request.user)
    return fy, fys, wards, d, P, work


@login_required
def cao_home(request):
    """प्रमुख प्रशासकीय अधिकृत — स्वीकृति र निगरानी."""
    from . import role_dash as rd

    if request.user.user_type not in ("1", "2"):
        return redirect("unauthorized")

    fy, fys, wards, d, P, work = _role_ctx(request)
    from .deductions import retention_items
    from .models import Project

    pq = Project.objects.all() if wards is None else Project.objects.filter(ward_id__in=wards)
    # धरौटी: फिर्ता योग्य / प्रक्रियामा (सबै आ.व. — अघिल्ला वर्षका दायित्व पनि)
    ret = [r for r in retention_items(list(pq.values_list("id", flat=True))) if r["status"] in ("due", "recommended", "tippani")]
    from usercommittee.workflow import bs_date

    for r in ret:
        r["due_bs"] = bs_date(r["due"]) if r["due"] else ""
    x = rd.cao(request.user, fy, wards, d)
    app_draft = reverse("app_list") + (f"?fiscalyear={fy.id}&status=draft" if fy else "")
    actions = [("स्वीकृति बाँकी", reverse("my_work"), "bell-ring", "urgent", x["approval_count"]),
               ("खरिद योजना", app_draft, "clipboard-list", "", 0),
               ("बजेट संशोधन", reverse("budget_amendments"), "file-pen-line", "", 0),
               ("अधिकार प्रत्यायोजन", reverse("uc_approvers"), "user-check", "", 0),
               ("प्रतिवेदनहरू", reverse("reports_hub"), "bar-chart-3", "", 0)]
    return render(request, "projects/home_cao.html", {
        "fy": fy, "fiscal_years": fys, "d": d, "x": x, "work_total": work["total"], "actions": actions,
        "guarantees": _guarantees_soon(wards) if P & {"bid.view", "quot.view"} else None,
        "retention": {"rows": ret[:4], "n": len(ret), "held": sum((r["held"] for r in ret), Decimal("0"))},
        "links": {"approve_uc": reverse("usercommittee_workflow") + "?stage=to_approve",
                  "app_draft": reverse("app_list") + (f"?fiscalyear={fy.id}&status=draft" if fy else ""),
                  "amend": reverse("budget_amendments"), "reports": reverse("reports_hub")},
    })


@login_required
def planning_dash(request):
    """योजना अधिकृत — योजना र खरिद व्यवस्थापन."""
    from . import role_dash as rd

    if request.user.user_type not in ("1", "3"):
        return redirect("unauthorized")

    fy, fys, wards, d, P, work = _role_ctx(request)
    x = rd.planning(request.user, fy, wards, d)
    q = f"?fiscalyear={fy.id}" if fy else ""
    actions = [("स्वीकृति बाँकी", reverse("my_work"), "stamp", "urgent", x["approval_count"])] if x["approval_count"] else []
    actions += [("नयाँ योजना", reverse("add_project"), "folder-plus", "", 0),
               ("Excel आयात", reverse("import_excel"), "file-spreadsheet", "", 0),
               ("विधि नतोकिएका", reverse("app_list") + (q + "&status=none" if q else ""), "alert-triangle", "urgent", x["kpi"]["no_method"]),
               ("उपभोक्ता समिति", reverse("usercommittee_workflow"), "users", "", 0),
               ("प्रतिवेदनहरू", reverse("reports_hub"), "bar-chart-3", "", 0)]
    return render(request, "projects/home_planning.html", {
        "fy": fy, "fiscal_years": fys, "d": d, "x": x, "work_total": work["total"], "actions": actions,
        "links": {"add": reverse("add_project"), "import": reverse("import_excel"),
                  "no_method": reverse("app_list") + (f"?fiscalyear={fy.id}&status=none" if fy else ""),
                  "app": reverse("app_list"), "uc": reverse("usercommittee_workflow"), "reports": reverse("reports_hub")},
    })


def _q(fy):
    return f"?fiscalyear={fy.id}" if fy else ""


@login_required
def account_dash(request):
    """लेखा अधिकृत — भुक्तानी, कर कट्टी, धरौटी र बजेट निकासा."""
    from . import role_dash as rd

    if request.user.user_type not in ("1", "10"):
        return redirect("unauthorized")
    fy, fys, wards, d, P, work = _role_ctx(request)
    x = rd.accounts(request.user, fy, wards, d)
    actions = [("भुक्तानी टिप्पणी बाँकी", reverse("my_work"), "file-check-2", "urgent", x["tippani_count"]),
               ("कर कट्टी विवरण", reverse("uc_report_taxes") + _q(fy), "receipt", "", 0),
               ("धरौटी फिर्ता", reverse("retention_list"), "hand-coins", "", 0),
               ("बजेट स्थिति", reverse("budget_status") + _q(fy), "wallet", "", 0)]
    return render(request, "projects/home_account.html", {
        "fy": fy, "fiscal_years": fys, "d": d, "x": x, "work_total": work["total"], "actions": actions,
    })


@login_required
def ward_dash(request):
    """वडा अध्यक्ष / वडा सचिव — आफ्नो वडाका योजना, सिफारिस र स्वीकृति."""
    from accounts.models import Ward

    from . import role_dash as rd

    t = request.user.user_type
    if t not in ("1", "6", "9"):
        return redirect("unauthorized")
    fy, fys, wards, d, P, work = _role_ctx(request)
    x = rd.ward(request.user, fy, wards, d)
    ward_obj = Ward.objects.filter(id=wards[0]).first() if wards else None
    wf = reverse("usercommittee_workflow")
    if t == "6":
        actions = [("सम्झौता सिफारिस", reverse("view_projects_for_recommendation"), "file-signature", "urgent", x["sifaris_count"]),
                   ("भुक्तानी सिफारिस", reverse("view_projects_for_completion_recommendation"), "badge-check", "", 0),
                   ("उपभोक्ता समिति", wf + "?stage=committee", "users", "", 0),
                   ("वडाका योजना", reverse("ward_project_list"), "folder-open", "", 0)]
    else:
        actions = [("स्वीकृति बाँकी", wf + "?stage=to_approve", "bell-ring", "urgent", x["approve_count"]),
                   ("उपभोक्ता समिति", wf, "users", "", 0),
                   ("साइट फोटो", reverse("field_home"), "camera", "", 0),
                   ("मेरो काम", reverse("my_work"), "list-checks", "", 0)]
    return render(request, "projects/home_ward.html", {
        "fy": fy, "fiscal_years": fys, "d": d, "x": x, "work_total": work["total"], "actions": actions,
        "ward_obj": ward_obj, "is_chair": t == "9", "is_sachib": t == "6",
    })


@login_required
def engineer_dash(request):
    """इन्जिनियर (पालिका / वडा) — लागत अनुमान, मूल्याङ्कन, साइट फोटो र धरौटी सिफारिस."""
    from accounts.models import Ward

    from . import role_dash as rd

    t = request.user.user_type
    if t not in ("1", "4", "7", "8"):
        return redirect("unauthorized")
    fy, fys, wards, d, P, work = _role_ctx(request)
    x = rd.engineer(request.user, fy, wards, d)
    ward_obj = Ward.objects.filter(id=wards[0]).first() if wards else None
    wf = reverse("usercommittee_workflow")
    actions = [("लागत अनुमान बाँकी", wf + "?stage=estimate", "calculator", "urgent", x["est_count"]),
               ("अन्तिम मूल्याङ्कन", wf + "?stage=valuation", "clipboard-check", "", x["val_count"]),
               ("साइट फोटो (GPS)", reverse("field_home"), "camera", "", 0),
               ("मेरो काम", reverse("my_work"), "list-checks", "", 0)]
    return render(request, "projects/home_engineer.html", {
        "fy": fy, "fiscal_years": fys, "d": d, "x": x, "work_total": work["total"], "actions": actions,
        "ward_obj": ward_obj, "role_label": {"7": "वडा इन्जिनियर", "8": "पालिका इन्जिनियर"}.get(t, "इन्जिनियर"),
    })
