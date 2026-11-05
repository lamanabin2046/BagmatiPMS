from decimal import Decimal, InvalidOperation
from datetime import date, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator

from nepali.date_converter import converter

from projects.models import Project, ProjectTimeline
from projects.outputs import catalog as outputs_catalog
from .models import UserCommittee, CostEstimate, FinalPayment, WardRecommendation, ProjectCompletionRecommendation, SiteInspectionNote, ActivityLog
from accounts.models import WardSachib, WardEngineer, PalikaEngineer, CustomUser
from .roster import POSTS, DOC_KINDS, GENDERS, default_rows, parse_roster, apply_roster, roster_rows, sync_members, with_slots
from accounts.permissions import has_perm
from .tax import active_heads, parse_tax_rows, tax_labels, tax_rows


def committee_access(request, project=None):
    """समिति गठन/सम्पादनको अनुमति ("uc.committee"), वडा तहका कर्मचारीले आफ्नै वडाको मात्र।"""
    if not has_perm(request.user, "uc.committee"):
        return False
    if project is not None:
        from .views_workflow import _user_wards

        wards = _user_wards(request.user)
        if wards is not None and project.ward_id not in wards:
            return False
    return True


BANK_FIELDS = ("bank_name", "bank_branch", "account_number", "account_name")


def apply_bank(uc, post):
    """समितिको बैंक खाता फारमबाट (save गर्दैन)."""
    for f in BANK_FIELDS:
        setattr(uc, f, (post.get(f) or "").strip()[:250])
    raw = (post.get("account_opened_date") or "").strip()
    uc.account_opened_date = convert_nepali_to_english(raw) if raw else None


def roster_ctx(rows, uc_id=None):
    import json

    from .conflicts import is_blocking, person_active_posts
    from .models import Person

    rows = with_slots(rows)
    for r in rows:  # अरू सक्रिय समितिमा भएको पद (फारममा चेतावनीका लागि)
        active = []
        if r.get("name") and (r.get("person_id") or r.get("nid") or r.get("citizenship")):
            person = r.get("person") or (Person.objects.filter(id=r["person_id"]).first() if r.get("person_id") else None)
            active = person_active_posts(person, r.get("nid", ""), r.get("citizenship", ""), uc_id)
        r["active_json"] = json.dumps(active, ensure_ascii=False)
    return {"rows": rows, "posts": POSTS, "doc_kinds": DOC_KINDS, "genders": GENDERS,
            "doc_slots_blank": [{"kind": k, "label": l, "url": "", "pdf": False} for k, l in DOC_KINDS],
            "nid_api": nid_service.api_configured(), "nid_mode": nid_service.api_mode(),
            "uc_id": uc_id or "", "conflict_block": is_blocking()}


def officer_conflict_check(request, rows, uc_id=None):
    """सुरक्षित गर्नुअघि: block नीति भए त्रुटि list फर्काउँछ; warn भए सन्देश (सुरक्षित पछि देखाउन)।"""
    from .conflicts import is_blocking, messages_for, roster_conflicts

    found = messages_for(roster_conflicts(rows, uc_id))
    if not found:
        return [], []
    if is_blocking():
        return [m + " (पालिकाको नियम अनुसार एकैपटक एउटै समितिमा मात्र पदाधिकारी हुन मिल्छ)" for m in found], []
    return [], found
from . import nid as nid_service
from django.http import JsonResponse


# ===================== म्याद / DEADLINE ALERT HELPER =====================
def usercommittee_deadline_alerts(limit=5, soon_days=30, ward=None):
    """Common data for the 'उपभोक्ता समिति म्याद अलर्ट' dashboard widget,
    shared by ADMIN_HOME, planning_home and palika_engineer_home.

    Returns expired/expiring counts (काम अझै 'Completed' नभएका र म्याद
    (extended_date भए सोही, नत्र accomplish_date) नाघेका/नाघ्न लागेका
    उपभोक्ता समिति) plus the soonest `limit` of them for a detail table.
    `ward` optionally scopes everything to one Ward (for role-specific
    dashboards that should only see their own ward — currently unused but
    kept for future Ward Sachib/Ward Engineer widgets).
    """
    today = date.today()
    soon_limit = today + timedelta(days=soon_days)

    qs = (
        UserCommittee.objects
        .exclude(status=2)
        .annotate(_deadline=Coalesce("extended_date", "accomplish_date"))
        .filter(_deadline__isnull=False)
    )
    if ward is not None:
        qs = qs.filter(project__ward=ward)

    expired_count = qs.filter(_deadline__lt=today).count()
    expiring_count = qs.filter(_deadline__gte=today, _deadline__lte=soon_limit).count()

    alert_committees = (
        qs.filter(_deadline__lte=soon_limit)
        .select_related("project", "project__ward")
        .order_by("_deadline")[:limit]
    )

    return {
        "usercommittee_expired_count": expired_count,
        "usercommittee_expiring_count": expiring_count,
        "usercommittee_deadline_alerts": alert_committees,
    }


# ===================== परिवर्तन लग (ACTIVITY LOG) =====================
def log_activity(request, action, instance, model_label, note=""):
    """Record one उपभोक्ता समिति / लागत अनुमान / अन्तिम भुक्तानी create/update
    event for the Admin-only 'परिवर्तन लग' page. Called explicitly right
    after the relevant .save()/.objects.create() in this file — kept as a
    plain function call rather than a signal so every entry always has the
    acting user attached, and so each view makes it obvious exactly what
    gets logged.

    object_id/object_repr/project_name are captured as a snapshot at log
    time, so the log entry stays meaningful even if the underlying record
    is later changed or (in future) deleted.
    """
    try:
        project = getattr(instance, "project", None)
        ActivityLog.objects.create(
            user=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
            action=action,
            model_name=model_label,
            object_id=instance.pk,
            object_repr=str(instance),
            project_name=project.name if project else None,
            note=note,
        )
    except Exception:
        # लग असफल भएकै कारणले मुख्य कार्य (सेभ/सिर्जना) रोकिनु हुँदैन।
        pass


def activity_log(request):
    """परिवर्तन लग — Admin-only audit trail of every उपभोक्ता समिति/लागत
    अनुमान/अन्तिम भुक्तानी create/update, with who-did-it and when."""
    if not (request.user.is_authenticated and getattr(request.user, "user_type", None) == '1'):
        return redirect("unauthorized")

    logs = ActivityLog.objects.select_related("user").order_by("-created_at")

    selected_action = request.GET.get("action", "")
    selected_model = request.GET.get("model", "")
    selected_user = request.GET.get("user", "")
    q = (request.GET.get("q") or "").strip()

    if selected_action:
        logs = logs.filter(action=selected_action)
    if selected_model:
        logs = logs.filter(model_name=selected_model)
    if selected_user:
        logs = logs.filter(user_id=selected_user)
    if q:
        logs = logs.filter(
            Q(project_name__icontains=q)
            | Q(object_repr__icontains=q)
            | Q(note__icontains=q)
        )
    # मिति (वि.सं.) अनुसार
    from datetime import datetime as _dt
    from datetime import time as _time

    from django.utils import timezone as _tz

    from biddings.views_workflow import to_ad
    sel_from, sel_to = (request.GET.get("from") or "").strip(), (request.GET.get("to") or "").strip()
    d_from, d_to = to_ad(sel_from), to_ad(sel_to)
    if d_from:
        logs = logs.filter(created_at__gte=_dt.combine(d_from, _time.min, _tz.get_current_timezone()))
    if d_to:
        logs = logs.filter(created_at__lte=_dt.combine(d_to, _time.max, _tz.get_current_timezone()))
    if request.GET.get("export") == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "गतिविधि लग"
        ws.append(["समय", "प्रयोगकर्ता", "कार्य", "किसिम", "विवरण", "योजना", "टिप्पणी"])
        for c in ws[1]:
            c.font = Font(bold=True)
        for x in logs[:50000]:
            ws.append([_tz.localtime(x.created_at).strftime("%Y-%m-%d %H:%M"), str(x.user) if x.user else "",
                       x.get_action_display(), x.model_name, x.object_repr, x.project_name or "", x.note])
        for col, w in zip("ABCDEFG", (18, 18, 12, 20, 44, 36, 44)):
            ws.column_dimensions[col].width = w
        from django.http import HttpResponse
        resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="activity-log.xlsx"'
        wb.save(resp)
        return resp

    total_count = logs.count()

    paginator = Paginator(logs, 50)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    model_choices = (
        ActivityLog.objects.order_by("model_name")
        .values_list("model_name", flat=True)
        .distinct()
    )
    log_users = CustomUser.objects.filter(
        id__in=ActivityLog.objects.exclude(user__isnull=True).values_list("user_id", flat=True).distinct()
    )

    context = {
        "page_obj": page_obj,
        "total_count": total_count,
        "action_choices": ActivityLog.ACTION_CHOICES,
        "model_choices": model_choices,
        "log_users": log_users,
        "selected_action": selected_action,
        "selected_model": selected_model,
        "selected_user": selected_user,
        "selected_q": q,
        "selected_from": sel_from,
        "selected_to": sel_to,
    }
    return render(request, "Admin/Settings/activity_log.html", context)


# ===================== ROLE HELPERS =====================
def get_ward_sachib_profile(request):
    """Return the WardSachib profile for the logged-in user, or None if
    the user isn't authenticated as a Ward Sachib. (Mirrors the same
    helper in accounts/views.py.)"""
    user = request.user
    if not user.is_authenticated or getattr(user, "user_type", None) != '6':
        return None
    return WardSachib.objects.select_related("ward").filter(admin=user).first()


def get_ward_engineer_profile(request):
    """Return the WardEngineer profile for the logged-in user, or None if
    the user isn't authenticated as a Ward Engineer. (Mirrors the same
    helper in accounts/views.py.)"""
    user = request.user
    if not user.is_authenticated or getattr(user, "user_type", None) != '7':
        return None
    return WardEngineer.objects.select_related("ward").filter(admin=user).first()


def get_palika_engineer_profile(request):
    """Return the PalikaEngineer profile for the logged-in user, or None
    if the user isn't authenticated as a Palika Engineer. Unlike
    get_ward_engineer_profile, this role isn't tied to any one ward —
    a Palika Engineer works across every ward's projects."""
    user = request.user
    if not user.is_authenticated or getattr(user, "user_type", None) != '8':
        return None
    return PalikaEngineer.objects.filter(admin=user).first()


DOC_TYPES = (".pdf", ".jpg", ".jpeg", ".png")
DOC_MAX_MB = 10


def doc_error(request):
    """ऐच्छिक कागजात (field "document") जाँच: PDF / JPG / PNG, १० MB सम्म. ठीक भए None."""
    f = request.FILES.get("document")
    if not f:
        return None
    if not f.name.lower().endswith(DOC_TYPES):
        return "कागजात PDF, JPG वा PNG मात्र हुनुपर्छ।"
    if f.size > DOC_MAX_MB * 1024 * 1024:
        return f"कागजात {DOC_MAX_MB} MB भन्दा सानो हुनुपर्छ।"
    return None


def apply_doc(request, obj):
    """नयाँ फाइल आए राख्ने, "document_clear" थिचे हटाउने (save गर्नुअघि बोलाउने)."""
    f = request.FILES.get("document")
    if f:
        obj.document = f
    elif request.POST.get("document_clear") and obj.document:
        obj.document = None


def is_planning_or_admin(request):
    """PLANNING OFFICER (3) and ADMIN (1) have full, unrestricted access
    to उपभोक्ता समिति creation/editing — including the योजना
    सुरु/समाप्त मिति fields that Ward Sachib users may not set."""
    user = request.user
    return user.is_authenticated and getattr(user, "user_type", None) in ("1", "3")


def devanagari_to_english_number(dev_num_str):
    devanagari_digits = '०१२३४५६७८९'
    english_digits = '0123456789'
    translation_table = str.maketrans(devanagari_digits, english_digits)
    return dev_num_str.translate(translation_table)


def convert_nepali_to_english(nepali_date_str):
    if nepali_date_str:
        try:
            nepali_year, nepali_month, nepali_day = map(int, nepali_date_str.split('-'))
            english_year, english_month, english_day = converter.nepali_to_english(nepali_year, nepali_month, nepali_day)
            return f"{english_year}-{english_month:02d}-{english_day:02d}"
        except ValueError:
            return None
    return None

def convert_english_to_nepali(english_date):
    if english_date and english_date != 'None':
        try:
            # If it's a date object, convert to string 'YYYY-MM-DD'
            if not isinstance(english_date, str):
                english_date = english_date.strftime('%Y-%m-%d')
                
            english_year, english_month, english_day = map(int, english_date.split('-'))
            nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
            return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
        except ValueError:
            return None
    return None





# ===================== DATE HELPERS =====================
def convert_nepali_to_english(nepali_date_str):
    if nepali_date_str:
        try:
            y, m, d = map(int, nepali_date_str.split('-'))
            ey, em, ed = converter.nepali_to_english(y, m, d)
            return f"{ey}-{em:02d}-{ed:02d}"
        except Exception:
            return None
    return None


# ===================== ADD USER COMMITTEE =====================
def add_usercommittee(request, project_id=None):
    """
    Two ways to reach this view:
      - /UserCommittee/add/                 (no project_id) — a dropdown
        of all pending projects. Used by Admin/Planning Officer.
      - /UserCommittee/add/<project_id>/    — locked to that one
        project, no dropdown. Used by Ward Sachib, who reaches this
        from a specific project's "समिति विवरण भर्नुहोस्" button on
        their own ward's योजना list, and must not be able to pick a
        different project (in or out of their ward) from a dropdown.
    """

    sachib = get_ward_sachib_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not committee_access(request):
        return redirect("unauthorized")

    # Ward Sachib must always arrive with a specific project id — they
    # never get the all-projects dropdown. Send them back to pick one.
    if sachib and project_id is None:
        return redirect("ward_project_list")

    locked_project = None
    if project_id is not None:
        locked_project = get_object_or_404(Project, id=project_id)
        # Ward Sachib may only fill in the committee for a project in
        # their own ward.
        if not committee_access(request, locked_project):
            return redirect("unauthorized")
        from projects.procurement import plan_gate
        if not hasattr(locked_project, "user_committee") and (gate := plan_gate(locked_project)):
            messages.error(request, gate)
            return redirect("app_plan", locked_project.id) if request.user.user_type in ("1", "3") else redirect(
                "usercommittee_workflow")

    if request.method == "POST":
        # The project comes from the locked URL id when present (so a
        # Ward Sachib can never override it via the submitted form);
        # only the dropdown flow (Admin/Planning Officer, no id in the
        # URL) reads it from the posted field.
        if locked_project is not None:
            project = locked_project
        else:
            project = get_object_or_404(Project, id=request.POST.get("project"))

        if hasattr(project, "user_committee"):
            messages.error(request, "यो परियोजनाको समिति पहिले नै बनेको छ।")
            if sachib:
                return redirect("ward_project_list")
            return redirect("add_usercommittee")
        from projects.procurement import plan_gate
        if (gate := plan_gate(project)):
            messages.error(request, gate)
            return redirect("add_usercommittee")

        formation_date = convert_nepali_to_english(request.POST.get("formation_date"))

        # योजना सुरु/समाप्त मिति — केवल योजना अधिकृत/एडमिनले मात्र भर्न
        # सक्ने। वडा सचिवले पेश गरे पनि यी बेवास्ता गरिन्छ।
        if staff_officer:
            start_date = convert_nepali_to_english(request.POST.get("start_date"))
            accomplish_date = convert_nepali_to_english(request.POST.get("accomplish_date"))
        else:
            start_date = None
            accomplish_date = None

        # ================= पदाधिकारी तथा सदस्य =================
        if not committee_access(request, project):
            return redirect("unauthorized")
        rows, errors = parse_roster(request.POST, request.FILES)
        conflict_errors, conflict_warnings = officer_conflict_check(request, rows) if not errors else ([], [])
        errors += conflict_errors
        if errors:
            for e in errors:
                messages.error(request, e)
            ctx = roster_ctx(rows or default_rows()) | {"form": request.POST}
            if locked_project is not None:
                ctx["project"] = locked_project
            else:
                ctx["projects"] = Project.objects.filter(procurement_type=1, status=0)
                ctx["selected_project"] = str(project.id)
            return render(request, "Admin/User/add_usercommittee.html", ctx)

        new_committee = UserCommittee(
            project=project,
            formation_date=formation_date,
            name=request.POST.get("name"),
            start_date=start_date,
            accomplish_date=accomplish_date,
            status=1,
        )
        apply_roster(new_committee, rows)
        new_committee.save()
        sync_members(new_committee, rows, request.user)
        log_activity(request, "create", new_committee, "उपभोक्ता समिति")
        for w in conflict_warnings:
            messages.warning(request, w)

        project.status = 2 if hasattr(project, "cost_estimate") else 1   # लागत अनुमान पहिले भइसकेको भए
        project.save()

        if sachib:
            messages.success(
                request,
                "उपभोक्ता समिति सफलतापूर्वक थपियो ✅ (योजना सुरु/समाप्त मिति पछि योजना शाखा/एडमिनबाट थपिनेछ)"
            )
            return redirect("ward_project_list")

        messages.success(request, "उपभोक्ता समिति सफलतापूर्वक थपियो ✅")
        return redirect("add_cost_estimate")

    # ================= GET =================
    if locked_project is not None:
        if hasattr(locked_project, "user_committee"):
            messages.info(request, "यो परियोजनाको समिति पहिले नै बनेको छ।")
            if sachib:
                return redirect("ward_project_list")
            return redirect("edit_usercommittee", id=locked_project.user_committee.id)
        return render(request, "Admin/User/add_usercommittee.html",
                      roster_ctx(default_rows()) | {"project": locked_project})

    projects = Project.objects.filter(procurement_type=1, status=0)
    return render(request, "Admin/User/add_usercommittee.html", roster_ctx(default_rows()) | {"projects": projects})

from decimal import Decimal

def add_cost_estimate(request, project_id=None):
    """
    Two ways to reach this view:
      - /UserCommittee/add-cost-estimate/               (no project_id) —
        a dropdown of all pending (status=1) projects. Used by
        Admin/Planning Officer.
      - /UserCommittee/add-cost-estimate/<project_id>/  — locked to that
        one project, no dropdown. Used by Ward Engineer for a project in
        their own ward, and by Palika Engineer for any project (no ward
        restriction — पालिका इन्जिनियर sees every ward).
    """
    engineer = get_ward_engineer_profile(request)
    palika_engineer = get_palika_engineer_profile(request)
    # योजना अधिकृत / Admin, वा "लागत अनुमान थप्ने" अनुमति भएका इन्जिनियर (भूमिका ४) — सबै वडा
    staff_officer = is_planning_or_admin(request) or (
        request.user.user_type == "4" and has_perm(request.user, "uc.estimate"))

    if not engineer and not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    if engineer and project_id is None:
        return redirect("ward_engineer_project_list")
    if palika_engineer and project_id is None:
        return redirect("palika_engineer_project_list")

    locked_project = None
    if project_id is not None:
        locked_project = get_object_or_404(Project, id=project_id)
        if engineer and locked_project.ward_id != engineer.ward_id:
            return redirect("unauthorized")

    if request.method == "POST":
        if locked_project is not None:
            project = locked_project
        else:
            project = get_object_or_404(Project, id=request.POST.get("project"))

        budget_raw = request.POST.get("budget")
        contingency_raw = request.POST.get("contingency_amount")
        user_contribution_raw = request.POST.get("user_contribution")

        # ================= VALIDATION =================
        if not all([budget_raw, contingency_raw, user_contribution_raw]):
            messages.error(request, "All fields are required.")
            if engineer or palika_engineer:
                return redirect("add_cost_estimate_for_project", project_id=project.id)
            return redirect("add_cost_estimate")

        try:
            budget = Decimal(budget_raw)
            contingency_amount = Decimal(contingency_raw)
            user_contribution = Decimal(user_contribution_raw)
        except InvalidOperation:
            messages.error(request, "Invalid number format.")
            if engineer or palika_engineer:
                return redirect("add_cost_estimate_for_project", project_id=project.id)
            return redirect("add_cost_estimate")

        if hasattr(project, "cost_estimate"):
            messages.error(request, "Cost estimate already exists for this project.")
            if engineer:
                return redirect("ward_engineer_project_list")
            if palika_engineer:
                return redirect("palika_engineer_project_list")
            return redirect("add_cost_estimate")

        from .amounts import check_estimate
        amount_errors, amount_warnings = check_estimate(project, budget, contingency_amount, user_contribution)
        if amount_errors:
            for e in amount_errors:
                messages.error(request, e)
            if locked_project is not None:
                return redirect("add_cost_estimate_for_project", project_id=project.id)
            return redirect("add_cost_estimate")

        total_cost = budget + user_contribution - contingency_amount

        if (err := doc_error(request)):
            messages.error(request, err)
            if locked_project is not None:
                return redirect("add_cost_estimate_for_project", project_id=project.id)
            return redirect("add_cost_estimate")
        new_estimate = CostEstimate(
            project=project,
            budget=budget,
            contingency_amount=contingency_amount,
            user_contribution=user_contribution,
            total_cost=total_cost,
            status=0
        )
        apply_doc(request, new_estimate)
        new_estimate.save()
        log_activity(request, "create", new_estimate, "लागत अनुमान")
        for w in amount_warnings:
            messages.warning(request, w)

        project.status = 2
        project.save()

        if engineer:
            messages.success(request, "लागत अनुमान सफलतापूर्वक थपियो ✅")
            return redirect("ward_engineer_project_list")

        if palika_engineer:
            messages.success(request, "लागत अनुमान सफलतापूर्वक थपियो ✅")
            return redirect("palika_engineer_project_list")

        messages.success(request, "लागत अनुमान सफलतापूर्वक थपियो ✅")
        return redirect("view_estimated_projects")

    # ================= GET =================
    if locked_project is not None:
        if hasattr(locked_project, "cost_estimate"):
            messages.info(request, "यो परियोजनाको लागत अनुमान पहिले नै थपिएको छ।")
            if engineer:
                return redirect("ward_engineer_project_list")
            if palika_engineer:
                return redirect("palika_engineer_project_list")
            return redirect("view_estimated_projects")
        return render(request, "Admin/User/add_cost_estimate.html", {"project": locked_project})

    # उपभोक्ता समिति विधिका, लागत अनुमान नभएका योजना (समिति गठन भए पनि नभए पनि), चालु आ.व.
    from projects.fiscal import current_fy_id
    from .workflow import workflow_queryset

    projects = workflow_queryset().filter(cost_estimate__isnull=True)
    if current_fy_id():
        projects = projects.filter(fiscalyear_id=current_fy_id())
    return render(request, "Admin/User/add_cost_estimate.html", {
        "projects": projects
    })


def view_estimated_projects(request):
    cost_estimate = CostEstimate.objects.select_related(
        "project", "project__ward", "project__ward_recommendation"
    ).order_by('-id')
    context = {

        "cost_estimate":cost_estimate
    }

    return render(request,"Admin/User/view_estimated_project.html",context)





def PRINT_TIPPANI(request, id):
    # Fetch the project and user committee
    project = Project.objects.get(id=id)
    usercommittee = UserCommittee.objects.get(project_id=id)
    start_date = usercommittee.start_date
    formation_date = usercommittee.formation_date

    # वडा सिफारिस is optional: the ward may send it through the portal or on paper.
    recommendation = getattr(project, "ward_recommendation", None)

    # Convert the start date from English to Nepali
    start_date_nepali = convert_english_to_nepali(start_date)
    formation_date_nepali = convert_english_to_nepali(formation_date)
    recommendation_date_nepali = convert_english_to_nepali(recommendation.recommendation_date) if recommendation else None


    # Prepare context for the template
    context = {
        "project": project,
        "usercommittee": usercommittee,
        "start_date_nepali": start_date_nepali , # Pass the converted Nepali date
        "formation_date_nepali":formation_date_nepali,
        "recommendation": recommendation,
        "recommendation_date_nepali": recommendation_date_nepali,
    }

    return render(request, "Admin/User/print_tippani.html", context)




def PRINT_BANK_LETTER(request,id):
    project = Project.objects.get(id = id)
    usercommittee = UserCommittee.objects.get(project_id = id)
    cost_estimate = CostEstimate.objects.get(project_id=id)
    start_date = usercommittee.start_date
    formation_date = usercommittee.formation_date
    accomplish_date = usercommittee.accomplish_date


    # Convert the start date from English to Nepali
    start_date_nepali = convert_english_to_nepali(start_date)
    formation_date_nepali = convert_english_to_nepali(formation_date)
    accomplish_date_nepali = convert_english_to_nepali(accomplish_date)
    
    context = {
        "project":project,
        "usercommittee":usercommittee,
        "cost_estimate":cost_estimate,
        "start_date_nepali":start_date_nepali,
        "formation_date_nepali":formation_date_nepali,
        "accomplish_date_nepali":accomplish_date_nepali
        
    }
    
    return render(request,"Admin/User/print_bank_letter.html",context)
    
    
def PRINT_WORK_ORDER(request,id):
    project = Project.objects.get(id = id)
    usercommittee = UserCommittee.objects.get(project_id = id)
    cost_estimate = CostEstimate.objects.get(project_id=id)
    start_date = usercommittee.start_date
    formation_date = usercommittee.formation_date
    accomplish_date = usercommittee.accomplish_date
  

    # Convert the start date from English to Nepali
    start_date_nepali = convert_english_to_nepali(start_date)
    formation_date_nepali = convert_english_to_nepali(formation_date)
    accomplish_date_nepali = convert_english_to_nepali(accomplish_date)
    
    context = {
        "project":project,
        "usercommittee":usercommittee,
        "cost_estimate":cost_estimate,
        "start_date_nepali":start_date_nepali,
        "formation_date_nepali":formation_date_nepali,
        "accomplish_date_nepali":accomplish_date_nepali
    }
    
    return render(request,"Admin/User/print_work_order.html",context)




def PRINT_CONTRACT_DOCUMENT(request,id):
    project = Project.objects.get(id = id)
    usercommittee = UserCommittee.objects.get(project_id=id)
    cost_estimate = CostEstimate.objects.get(project_id = id)
    office = cost_estimate.budget-cost_estimate.contingency_amount

    # वडा सिफारिस is optional: the ward may send it through the portal or on paper.
    recommendation = getattr(project, "ward_recommendation", None)

    start_date = usercommittee.start_date
    formation_date = usercommittee.formation_date
    accomplish_date = usercommittee.accomplish_date
        # Function to convert English date to Nepali date


    # Convert the start date from English to Nepali
    start_date_nepali = convert_english_to_nepali(start_date)
    formation_date_nepali = convert_english_to_nepali(formation_date)
    accomplish_date_nepali = convert_english_to_nepali(accomplish_date)
    recommendation_date_nepali = convert_english_to_nepali(recommendation.recommendation_date) if recommendation else None


    context = {
        "project":project,
        "usercommittee":usercommittee,
        "cost_estimate" :cost_estimate,
        "office":office,
        "start_date_nepali":start_date_nepali,
        "formation_date_nepali":formation_date_nepali,
        "accomplish_date_nepali":accomplish_date_nepali,
        "recommendation":recommendation,
        "recommendation_date_nepali":recommendation_date_nepali,

    }
    return render(request,"Admin/User/print_contract_paper.html",context)


# ===================== वडा सचिव सिफारिस =====================
# (get_ward_sachib_profile is defined once, near the top of this file.)


def ward_project_list(request):
    """List every project in the logged-in Ward Sachib's own ward, so
    they can create (or edit) the उपभोक्ता समिति for it. This is the
    Sachib's entry point into the workflow — it comes before the cost
    estimate and सिफारिस steps."""
    sachib = get_ward_sachib_profile(request)
    if not sachib:
        return redirect("unauthorized")

    projects = Project.objects.filter(
        ward=sachib.ward
    ).select_related("user_committee", "fiscalyear").order_by("-id")

    return render(request, "WardSachib/projects.html", {
        "sachib": sachib,
        "projects": projects,
    })


# ===================== वडा इन्जिनियर लागत अनुमान =====================
# (get_ward_engineer_profile is defined once, near the top of this file.)


def ward_engineer_project_list(request):
    """List every project in the logged-in Ward Engineer's own ward, so
    they can enter the लागत अनुमान (cost estimate) for it. Mirrors
    ward_project_list, one step later in the workflow — after the
    उपभोक्ता समिति has been formed (status=1)."""
    engineer = get_ward_engineer_profile(request)
    if not engineer:
        return redirect("unauthorized")

    projects = Project.objects.filter(
        ward=engineer.ward
    ).select_related("user_committee", "cost_estimate", "fiscalyear").order_by("-id")

    return render(request, "WardEngineer/projects.html", {
        "engineer": engineer,
        "projects": projects,
    })


def ward_engineer_project_photos(request, project_id):
    """फोटो टाइमलाइन — काम सुरु हुनु अघि / भइरहेको बेला / सम्पन्न भएपछि.
    The Ward Engineer must photograph each project at these three
    checkpoints (with a description), building a running timeline.
    Locked to a single project via the URL, same as
    add_usercommittee_for_project/add_cost_estimate_for_project — no
    dropdown. Ward Engineer is restricted to their own ward and can
    upload; Planning Officer/Admin have unrestricted upload access to
    any project; Ward Sachib may view (read-only, own ward only) so
    they can check site progress before issuing a सिफारिस; Palika
    Engineer may also view (read-only, any ward — पालिका इन्जिनियर
    covers every वडा)."""
    engineer = get_ward_engineer_profile(request)
    sachib = get_ward_sachib_profile(request)
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    can_upload = bool(engineer) or staff_officer
    can_view = can_upload or bool(sachib) or bool(palika_engineer)

    if not can_view:
        return redirect("unauthorized")

    project = get_object_or_404(Project, id=project_id)

    if engineer and project.ward_id != engineer.ward_id:
        return redirect("unauthorized")

    if sachib and project.ward_id != sachib.ward_id:
        return redirect("unauthorized")

    if request.method == "POST":
        if not can_upload:
            return redirect("unauthorized")

        image = request.FILES.get("image")
        description = request.POST.get("description")
        stage_raw = request.POST.get("stage")

        if not all([image, description, stage_raw]):
            messages.error(request, "चरण, फोटो र विवरण — सबै आवश्यक छन्।")
            return redirect("ward_engineer_project_photos", project_id=project.id)

        try:
            stage = int(stage_raw)
        except (TypeError, ValueError):
            stage = None

        if stage not in dict(ProjectTimeline.STAGE_CHOICES):
            messages.error(request, "मान्य चरण छान्नुहोस्।")
            return redirect("ward_engineer_project_photos", project_id=project.id)

        ProjectTimeline.objects.create(
            project=project,
            stage=stage,
            image=image,
            description=description,
            uploaded_by=request.user,
        )
        messages.success(request, "फोटो सफलतापूर्वक थपियो ✅")
        return redirect("ward_engineer_project_photos", project_id=project.id)

    photos = project.timelines.order_by("-created_at")

    return render(request, "WardEngineer/project_photos.html", {
        "project": project,
        "photos": photos,
        "engineer": engineer,
        "sachib": sachib,
        "can_upload": can_upload,
        "stage_choices": ProjectTimeline.STAGE_CHOICES,
        "before_count": photos.filter(stage=ProjectTimeline.STAGE_BEFORE).count(),
        "during_count": photos.filter(stage=ProjectTimeline.STAGE_DURING).count(),
        "after_count": photos.filter(stage=ProjectTimeline.STAGE_AFTER).count(),
    })


def palika_engineer_project_list(request):
    """List every project across every ward, so the logged-in Palika
    Engineer can enter or edit the लागत अनुमान (cost estimate) for any
    of them. Mirrors ward_engineer_project_list, but municipality-wide
    instead of scoped to one ward. Supports optional GET filters —
    ward, fiscal year, and लागत अनुमान status — since this list can
    span every project in the palika. Available to Admin/Planning
    Officer too, same as the other Palika Engineer reports."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    from accounts.models import Ward as _Ward
    from projects.models import FiscalYear as _FiscalYear

    projects = Project.objects.select_related(
        "ward", "user_committee", "cost_estimate", "fiscalyear"
    ).order_by("-id")

    selected_ward = request.GET.get("ward", "")
    selected_fiscalyear = request.GET.get("fiscalyear", "")
    selected_status = request.GET.get("status", "")

    if selected_ward:
        projects = projects.filter(ward_id=selected_ward)
    if selected_fiscalyear:
        projects = projects.filter(fiscalyear_id=selected_fiscalyear)
    if selected_status == "done":
        projects = projects.filter(cost_estimate__isnull=False)
    elif selected_status == "pending":
        projects = projects.filter(cost_estimate__isnull=True, procurement_type=1)
    elif selected_status == "no_committee":
        projects = projects.filter(user_committee__isnull=True)

    return render(request, "PalikaEngineer/projects.html", {
        "palika_engineer": palika_engineer,
        "projects": projects,
        "wards": _Ward.objects.order_by("name"),
        "fiscalyears": _FiscalYear.objects.order_by("-id"),
        "selected_ward": selected_ward,
        "selected_fiscalyear": selected_fiscalyear,
        "selected_status": selected_status,
    })


def edit_cost_estimate(request, id):
    """Edit an existing लागत अनुमान. Available to Admin/Planning Officer
    and Palika Engineer — locked once the project has moved past this
    stage (वडा सिफारिस जारी भएको वा अन्तिम भुक्तानी भइसकेको) so a later
    edit can never silently invalidate a सम्झौता/भुक्तानी that was
    already issued against the original figures."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    cost_estimate = get_object_or_404(CostEstimate, id=id)
    project = cost_estimate.project

    if hasattr(project, "ward_recommendation") or hasattr(project, "final_payment"):
        messages.error(
            request,
            "वडा सिफारिस वा अन्तिम भुक्तानी भइसकेकोले यो लागत अनुमान अब सम्पादन गर्न मिल्दैन।"
        )
        if palika_engineer:
            return redirect("palika_engineer_project_list")
        return redirect("view_estimated_projects")

    if request.method == "POST":
        budget_raw = request.POST.get("budget")
        contingency_raw = request.POST.get("contingency_amount")
        user_contribution_raw = request.POST.get("user_contribution")

        try:
            budget = Decimal(budget_raw)
            contingency_amount = Decimal(contingency_raw)
            user_contribution = Decimal(user_contribution_raw)
        except (InvalidOperation, TypeError):
            messages.error(request, "Invalid number format.")
            return redirect("edit_cost_estimate", id=id)

        from .amounts import check_estimate
        amount_errors, amount_warnings = check_estimate(project, budget, contingency_amount, user_contribution)
        if amount_errors:
            for e in amount_errors:
                messages.error(request, e)
            return redirect("edit_cost_estimate", id=id)
        for w in amount_warnings:
            messages.warning(request, w)

        cost_estimate.budget = budget
        cost_estimate.contingency_amount = contingency_amount
        cost_estimate.user_contribution = user_contribution
        cost_estimate.total_cost = budget + user_contribution - contingency_amount
        if (err := doc_error(request)):
            messages.error(request, err)
            return redirect("edit_cost_estimate", id=id)
        apply_doc(request, cost_estimate)
        cost_estimate.save()
        log_activity(request, "update", cost_estimate, "लागत अनुमान")

        messages.success(request, "लागत अनुमान सफलतापूर्वक सम्पादन गरियो ✅")
        if palika_engineer:
            return redirect("palika_engineer_project_list")
        return redirect("view_estimated_projects")

    return render(request, "PalikaEngineer/edit_cost_estimate.html", {
        "project": project,
        "cost_estimate": cost_estimate,
    })


# ===================== पालिका इन्जिनियर — थप पृष्ठहरू =====================

def palika_engineer_project_detail(request, id):
    """योजना विस्तृत विवरण — a single consolidated technical view of one
    project's full history: उपभोक्ता समिति, लागत अनुमान, वडा सिफारिस,
    फोटो टाइमलाइन, अन्तिम मूल्याङ्कन, काम सम्पन्न सिफारिस, हस्तान्तरण
    status, and प्राविधिक टिप्पणी — everything a Palika Engineer would
    otherwise have to visit several different pages to see."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    project = get_object_or_404(
        Project.objects.select_related(
            "ward", "fiscalyear", "user_committee", "cost_estimate",
            "ward_recommendation", "final_payment", "completion_recommendation",
        ),
        id=id,
    )

    photos = project.timelines.order_by("-created_at")
    inspection_notes = project.inspection_notes.select_related("palika_engineer").order_by("-created_at")

    context = {
        "palika_engineer": palika_engineer,
        "project": project,
        "usercommittee": getattr(project, "user_committee", None),
        "cost_estimate": getattr(project, "cost_estimate", None),
        "ward_recommendation": getattr(project, "ward_recommendation", None),
        "final_valuation": getattr(project, "final_payment", None),
        "completion_recommendation": getattr(project, "completion_recommendation", None),
        "photos": photos,
        "before_count": photos.filter(stage=ProjectTimeline.STAGE_BEFORE).count(),
        "during_count": photos.filter(stage=ProjectTimeline.STAGE_DURING).count(),
        "after_count": photos.filter(stage=ProjectTimeline.STAGE_AFTER).count(),
        "inspection_notes": inspection_notes,
    }
    return render(request, "PalikaEngineer/project_detail.html", context)


def add_site_inspection_note(request, project_id):
    """Palika Engineer logs a dated site-visit / technical remark
    against a project — their own oversight trail, independent of the
    Ward Engineer's photo timeline. A project can accumulate several
    notes over its life."""
    palika_engineer = get_palika_engineer_profile(request)
    if not palika_engineer:
        return redirect("unauthorized")

    project = get_object_or_404(Project, id=project_id)

    if request.method == "POST":
        remarks = (request.POST.get("remarks") or "").strip()

        if not remarks:
            messages.error(request, "कैफियत/टिप्पणी लेख्नुहोस्।")
            return redirect("palika_engineer_project_detail", id=project.id)

        inspection_date = convert_nepali_to_english(request.POST.get("inspection_date"))

        SiteInspectionNote.objects.create(
            project=project,
            palika_engineer=palika_engineer,
            inspection_date=inspection_date,
            remarks=remarks,
        )
        messages.success(request, "प्राविधिक टिप्पणी सफलतापूर्वक थपियो ✅")

    return redirect("palika_engineer_project_detail", id=project.id)


def palika_engineer_estimated_projects(request):
    """लागत अनुमान भएका योजनाहरू — प्रतिवेदन. Palika Engineer's own
    role-scoped copy of the Admin view_estimated_project report, so
    they don't need admin access to pull this list. Admin/Planning
    Officer can reach it too."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    cost_estimates = CostEstimate.objects.select_related(
        "project", "project__ward", "project__ward_recommendation"
    ).order_by("-id")

    return render(request, "PalikaEngineer/estimated_projects_report.html", {
        "palika_engineer": palika_engineer,
        "cost_estimate": cost_estimates,
    })


def download_palika_engineer_estimated_projects_excel(request):
    """Excel export of the same लागत अनुमान report above."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from django.http import HttpResponse

    cost_estimates = CostEstimate.objects.select_related(
        "project", "project__ward", "project__ward_recommendation"
    ).order_by("-id")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cost Estimates"

    headers = [
        "क्र. सं.", "योजनाको नाम", "वडा", "विनियोजित रकम",
        "कन्टेन्जेन्सी", "श्रमदान", "लागत अनुमान", "वडा सिफारिस स्थिति",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    thin_border = Border(*(Side(style="thin"),) * 4)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    for idx, i in enumerate(cost_estimates, start=1):
        row = [
            idx,
            i.project.name,
            i.project.ward.name if i.project.ward else "",
            float(i.budget),
            float(i.contingency_amount),
            float(i.user_contribution),
            float(i.total_cost),
            "जारी भयो" if hasattr(i.project, "ward_recommendation") else "बाँकी",
        ]
        ws.append(row)

    for r in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in r:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    widths = [8, 34, 14, 16, 14, 14, 16, 18]
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = width

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="palika_engineer_cost_estimates.xlsx"'
    wb.save(response)
    return response


def palika_engineer_ward_comparison(request):
    """वडा अनुसार तुलना — the one report only a municipality-wide role
    can meaningfully use: per-ward project counts by लागत अनुमान stage,
    and per-ward बजेट उपयोग, so lagging wards are easy to spot.
    Admin/Planning Officer can reach it too."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    import json as _json
    from accounts.models import Ward as _Ward

    ward_rows = []
    ward_labels, ward_estimate_done, ward_estimate_pending, ward_committee_pending = [], [], [], []
    ward_utilization = []

    for w in _Ward.objects.order_by("name"):
        ward_projects = Project.objects.filter(ward=w)
        total = ward_projects.count()
        committee_pending = ward_projects.filter(user_committee__isnull=True).count()
        estimate_pending = ward_projects.filter(user_committee__isnull=False, cost_estimate__isnull=True).count()
        estimate_done = ward_projects.filter(cost_estimate__isnull=False).count()
        completed = ward_projects.filter(completion_recommendation__isnull=False).count()

        budget_raw = ward_projects.aggregate(total=Sum("budget"))["total"] or 0
        budget = Decimal(str(budget_raw))
        estimated_amount = ward_projects.filter(cost_estimate__isnull=False).aggregate(
            total=Sum("cost_estimate__total_cost")
        )["total"] or Decimal("0")
        utilization_percent = (
            (estimated_amount / budget) * Decimal("100") if budget > 0 else Decimal("0")
        )

        ward_rows.append({
            "ward": w,
            "total": total,
            "committee_pending": committee_pending,
            "estimate_pending": estimate_pending,
            "estimate_done": estimate_done,
            "completed": completed,
            "budget": budget,
            "estimated_amount": estimated_amount,
            "utilization_percent": utilization_percent,
        })

        ward_labels.append(w.name)
        ward_estimate_done.append(estimate_done)
        ward_estimate_pending.append(estimate_pending)
        ward_committee_pending.append(committee_pending)
        ward_utilization.append(float(utilization_percent))

    context = {
        "palika_engineer": palika_engineer,
        "ward_rows": ward_rows,
        "ward_labels_json": _json.dumps(ward_labels),
        "ward_estimate_done_json": _json.dumps(ward_estimate_done),
        "ward_estimate_pending_json": _json.dumps(ward_estimate_pending),
        "ward_committee_pending_json": _json.dumps(ward_committee_pending),
        "ward_utilization_json": _json.dumps(ward_utilization),
    }
    return render(request, "PalikaEngineer/ward_comparison.html", context)


def palika_engineer_committee_list(request):
    """उपभोक्ता समिति सूची — every committee across every ward, read-only,
    so a Palika Engineer can see which wards have formed committees
    without going through the full project table. Admin/Planning
    Officer can reach it too."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    committees = UserCommittee.objects.select_related(
        "project", "project__ward", "project__cost_estimate"
    ).order_by("-id")

    return render(request, "PalikaEngineer/committees.html", {
        "palika_engineer": palika_engineer,
        "committees": committees,
    })


def palika_engineer_final_valuations(request):
    """अन्तिम मूल्याङ्कन — read-only visibility across every ward, so a
    Palika Engineer can compare the original लागत अनुमान against what
    was actually billed at the end of each project. Admin/Planning
    Officer can reach it too."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    final_payments = FinalPayment.objects.select_related(
        "project", "project__ward", "project__cost_estimate"
    ).order_by("-id")

    return render(request, "PalikaEngineer/final_valuations.html", {
        "palika_engineer": palika_engineer,
        "final_payments": final_payments,
    })


def _filter_committees_for_report(request):
    """Shared by the उपभोक्ता समिति वित्तीय प्रतिवेदन screen and its Excel
    export, so the two always agree on exactly which rows are included.
    Supports वडा, आ.व., and a स्थिति (workflow-stage) filter, each with
    an implicit "सबै" (all) option when left blank."""
    committees = UserCommittee.objects.select_related(
        "project", "project__ward", "project__fiscalyear",
        "project__cost_estimate", "project__final_payment",
    ).order_by("-id")

    selected_ward = request.GET.get("ward", "")
    selected_fiscalyear = request.GET.get("fiscalyear", "")
    selected_status = request.GET.get("status", "")

    if selected_ward:
        committees = committees.filter(project__ward_id=selected_ward)
    if selected_fiscalyear:
        committees = committees.filter(project__fiscalyear_id=selected_fiscalyear)
    if selected_status == "estimate_done":
        committees = committees.filter(project__cost_estimate__isnull=False)
    elif selected_status == "estimate_pending":
        committees = committees.filter(project__cost_estimate__isnull=True)
    elif selected_status == "paid":
        committees = committees.filter(project__final_payment__isnull=False)
    elif selected_status == "not_paid":
        committees = committees.filter(project__final_payment__isnull=True)

    return committees, selected_ward, selected_fiscalyear, selected_status


def _committee_report_totals(committees_qs):
    """The 7 aggregate figures shown at the top of the report and
    repeated in the Excel export's summary block. Every project here
    has a उपभोक्ता समिति (that's the base queryset), but a project may
    not yet have a लागत अनुमान or अन्तिम भुक्तानी — those legs are
    summed as 0 until they exist, same convention used everywhere else
    in this app (aggregate(...)["total"] or Decimal("0"))."""
    total_committee_projects = committees_qs.count()

    total_budget_raw = committees_qs.aggregate(total=Sum("project__budget"))["total"] or 0
    total_budget = Decimal(str(total_budget_raw))

    total_estimated = committees_qs.aggregate(
        total=Sum("project__cost_estimate__total_cost")
    )["total"] or Decimal("0")
    total_contingency = committees_qs.aggregate(
        total=Sum("project__cost_estimate__contingency_amount")
    )["total"] or Decimal("0")

    total_evaluated = committees_qs.aggregate(
        total=Sum("project__final_payment__final_evaluation")
    )["total"] or Decimal("0")
    total_tax_deducted = committees_qs.aggregate(
        total=Sum("project__final_payment__total_tax")
    )["total"] or Decimal("0")

    # net_payment (भुक्तानी रकम) is a Python @property on FinalPayment
    # (office_contribution - total_tax), not a DB column, so it can't
    # go through .aggregate(Sum(...)) — sum it in Python instead. The
    # queryset is already select_related'd by the caller, so this does
    # not trigger extra per-row queries.
    total_paid = sum(
        (c.project.final_payment.net_payment for c in committees_qs
         if hasattr(c.project, "final_payment")),
        Decimal("0"),
    )

    return {
        "total_committee_projects": total_committee_projects,
        "total_budget": total_budget,
        "total_estimated": total_estimated,
        "total_contingency": total_contingency,
        "total_evaluated": total_evaluated,
        "total_paid": total_paid,
        "total_tax_deducted": total_tax_deducted,
    }


def palika_engineer_committee_financial_report(request):
    """उपभोक्ता समिति वित्तीय प्रतिवेदन — every project that has a
    उपभोक्ता समिति formed, with its full financial picture: बजेट, लागत
    अनुमान, कन्टेन्जेन्सी, अन्तिम मुल्याङ्कन, भुक्तानी रकम, and कर कट्टी
    रकम — both as page-top totals and a row-by-row table, filterable by
    वडा and आ.व. (each with an "सबै" option) plus workflow स्थिति."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    from accounts.models import Ward as _Ward
    from projects.models import FiscalYear as _FiscalYear

    committees, selected_ward, selected_fiscalyear, selected_status = _filter_committees_for_report(request)
    totals = _committee_report_totals(committees)

    context = {
        "palika_engineer": palika_engineer,
        "committees": committees,
        "wards": _Ward.objects.order_by("name"),
        "fiscalyears": _FiscalYear.objects.order_by("-id"),
        "selected_ward": selected_ward,
        "selected_fiscalyear": selected_fiscalyear,
        "selected_status": selected_status,
    }
    context.update(totals)
    return render(request, "PalikaEngineer/committee_financial_report.html", context)


def download_committee_financial_report_excel(request):
    """Excel export of the same उपभोक्ता समिति वित्तीय प्रतिवेदन above —
    same filters (read from the querystring), same totals, plus a
    row-by-row breakdown sheet."""
    palika_engineer = get_palika_engineer_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not palika_engineer and not staff_officer:
        return redirect("unauthorized")

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from django.http import HttpResponse

    committees, selected_ward, selected_fiscalyear, selected_status = _filter_committees_for_report(request)
    totals = _committee_report_totals(committees)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Committee Report"

    bold = Font(bold=True)
    ws.append(["उपभोक्ता समिति वित्तीय प्रतिवेदन"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])

    summary_rows = [
        ("कुल उपभोक्ता समिति भएका योजना", totals["total_committee_projects"]),
        ("कुल बजेट", float(totals["total_budget"])),
        ("कुल लागत अनुमान", float(totals["total_estimated"])),
        ("कुल कन्टेन्जेन्सी", float(totals["total_contingency"])),
        ("कुल मुल्याङ्कन रकम", float(totals["total_evaluated"])),
        ("कुल भुक्तानी रकम", float(totals["total_paid"])),
        ("कुल कर कट्टी रकम", float(totals["total_tax_deducted"])),
    ]
    for label, value in summary_rows:
        ws.append([label, value])
        ws.cell(row=ws.max_row, column=1).font = bold

    ws.append([])

    header_row_idx = ws.max_row + 1
    headers = [
        "क्र. सं.", "योजनाको नाम", "वडा", "आ.व.", "बजेट",
        "लागत अनुमान", "कन्टेन्जेन्सी", "मुल्याङ्कन रकम", "भुक्तानी रकम", "कर कट्टी रकम",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    thin_border = Border(*(Side(style="thin"),) * 4)

    for cell in ws[header_row_idx]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    for idx, c in enumerate(committees, start=1):
        project = c.project
        cost_estimate = getattr(project, "cost_estimate", None)
        final_payment = getattr(project, "final_payment", None)
        row = [
            idx,
            project.name,
            project.ward.name if project.ward else "",
            project.fiscalyear.name if project.fiscalyear else "",
            float(project.budget),
            float(cost_estimate.total_cost) if cost_estimate else "",
            float(cost_estimate.contingency_amount) if cost_estimate else "",
            float(final_payment.final_evaluation) if final_payment else "",
            float(final_payment.net_payment) if final_payment else "",
            float(final_payment.total_tax) if final_payment else "",
        ]
        ws.append(row)

    for r in ws.iter_rows(min_row=header_row_idx + 1, max_row=ws.max_row):
        for cell in r:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    widths = [8, 34, 12, 14, 16, 16, 14, 16, 16, 14]
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=header_row_idx, column=col_idx).column_letter].width = width

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="usercommittee_financial_report.xlsx"'
    wb.save(response)
    return response


def view_projects_for_recommendation(request):
    """List (for the logged-in Ward Sachib) the projects in their own
    ward that have a cost estimate ready, along with the सिफारिस status
    of each — pending or already issued."""
    sachib = get_ward_sachib_profile(request)
    if not sachib:
        return redirect('unauthorized')

    projects = Project.objects.filter(
        ward=sachib.ward,
        cost_estimate__isnull=False,
    ).select_related(
        "cost_estimate", "user_committee", "ward_recommendation"
    ).order_by('-id')

    return render(request, "WardSachib/view_projects.html", {
        "sachib": sachib,
        "projects": projects,
    })


def add_ward_recommendation(request, id):
    """Ward Sachib issues the सिफारिस for a project in their own ward.
    Restricted to the Sachib assigned to that project's ward."""
    sachib = get_ward_sachib_profile(request)
    if not sachib:
        return redirect('unauthorized')

    project = get_object_or_404(Project, id=id, ward=sachib.ward)

    if not hasattr(project, "cost_estimate"):
        messages.error(request, "यो योजनाको लागत अनुमान अझै तयार भएको छैन।")
        return redirect('view_projects_for_recommendation')

    if hasattr(project, "ward_recommendation"):
        messages.info(request, "यो योजनाको सिफारिस पहिले नै जारी भइसकेको छ।")
        return redirect('print_ward_recommendation', id=project.id)

    if request.method == "POST":
        recommendation_date = convert_nepali_to_english(
            request.POST.get("recommendation_date")
        )
        WardRecommendation.objects.create(
            project=project,
            ward_sachib=sachib,
            letter_number=request.POST.get("letter_number"),
            chalani_number=request.POST.get("chalani_number"),
            recommendation_date=recommendation_date,
            remarks=request.POST.get("remarks"),
        )
        messages.success(request, "सिफारिस सफलतापूर्वक तयार गरियो ✅")
        return redirect('print_ward_recommendation', id=project.id)

    usercommittee = getattr(project, "user_committee", None)
    cost_estimate = getattr(project, "cost_estimate", None)

    return render(request, "WardSachib/add_recommendation.html", {
        "sachib": sachib,
        "project": project,
        "usercommittee": usercommittee,
        "cost_estimate": cost_estimate,
    })


def print_ward_recommendation(request, id):
    project = get_object_or_404(Project, id=id)
    recommendation = get_object_or_404(WardRecommendation, project=project)
    usercommittee = getattr(project, "user_committee", None)
    cost_estimate = getattr(project, "cost_estimate", None)

    context = {
        "project": project,
        "recommendation": recommendation,
        "usercommittee": usercommittee,
        "cost_estimate": cost_estimate,
        "recommendation_date_nepali": convert_english_to_nepali(
            recommendation.recommendation_date
        ),
        # आम भेला (general assembly) date the उपभोक्ता समिति was formed on
        "formation_date_nepali": convert_english_to_nepali(
            usercommittee.formation_date
        ) if usercommittee else None,
    }
    return render(request, "WardSachib/print_recommendation.html", context)


# ===================== वडा सचिव काम सम्पन्न सिफारिस =====================
# (Second, later-stage सिफारिस — certifies work completion, required
# before the हस्तान्तरण पत्र/handover letter. Mirrors the three views
# above, one workflow stage later: cost_estimate → final_payment,
# ward_recommendation → completion_recommendation.)

def view_projects_for_completion_recommendation(request):
    """List (for the logged-in Ward Sachib) the projects in their own
    ward whose अन्तिम मूल्याङ्कन (final valuation) has been added — i.e.
    work is effectively complete — along with the काम सम्पन्न सिफारिस
    status of each."""
    sachib = get_ward_sachib_profile(request)
    if not sachib:
        return redirect('unauthorized')

    projects = Project.objects.filter(
        ward=sachib.ward,
        final_payment__isnull=False,
    ).select_related(
        "final_payment", "user_committee", "completion_recommendation"
    ).order_by('-id')

    return render(request, "WardSachib/view_completion_projects.html", {
        "sachib": sachib,
        "projects": projects,
    })


def add_completion_recommendation(request, id):
    """Ward Sachib certifies that a project's work is complete, for a
    project in their own ward. Required before the हस्तान्तरण पत्र
    (handover letter) can be printed. Shows the Ward Engineer's photo
    timeline (सुरु अघि/भइरहेको/सम्पन्न भएपछि) inline so the Sachib can
    verify actual site progress before signing off."""
    sachib = get_ward_sachib_profile(request)
    if not sachib:
        return redirect('unauthorized')

    project = get_object_or_404(Project, id=id, ward=sachib.ward)

    if not hasattr(project, "final_payment"):
        messages.error(request, "यो योजनाको अन्तिम मूल्याङ्कन अझै तयार भएको छैन।")
        return redirect('view_projects_for_completion_recommendation')

    if hasattr(project, "completion_recommendation"):
        messages.info(request, "यो योजनाको काम सम्पन्न सिफारिस पहिले नै जारी भइसकेको छ।")
        return redirect('print_completion_recommendation', id=project.id)

    if request.method == "POST":
        recommendation_date = convert_nepali_to_english(
            request.POST.get("recommendation_date")
        )
        ProjectCompletionRecommendation.objects.create(
            project=project,
            ward_sachib=sachib,
            letter_number=request.POST.get("letter_number"),
            chalani_number=request.POST.get("chalani_number"),
            recommendation_date=recommendation_date,
            remarks=request.POST.get("remarks"),
        )
        messages.success(request, "काम सम्पन्न सिफारिस सफलतापूर्वक जारी गरियो ✅")
        return redirect('print_completion_recommendation', id=project.id)

    usercommittee = getattr(project, "user_committee", None)
    final_valuation = getattr(project, "final_payment", None)
    photos = project.timelines.order_by("-created_at")

    return render(request, "WardSachib/add_completion_recommendation.html", {
        "sachib": sachib,
        "project": project,
        "usercommittee": usercommittee,
        "final_valuation": final_valuation,
        "photos": photos,
        "before_count": photos.filter(stage=ProjectTimeline.STAGE_BEFORE).count(),
        "during_count": photos.filter(stage=ProjectTimeline.STAGE_DURING).count(),
        "after_count": photos.filter(stage=ProjectTimeline.STAGE_AFTER).count(),
    })


def print_completion_recommendation(request, id):
    project = get_object_or_404(Project, id=id)
    recommendation = get_object_or_404(ProjectCompletionRecommendation, project=project)
    usercommittee = getattr(project, "user_committee", None)
    final_valuation = getattr(project, "final_payment", None)

    context = {
        "project": project,
        "recommendation": recommendation,
        "usercommittee": usercommittee,
        "final_valuation": final_valuation,
        "recommendation_date_nepali": convert_english_to_nepali(
            recommendation.recommendation_date
        ),
        "accomplish_date_nepali": convert_english_to_nepali(
            usercommittee.accomplish_date
        ) if usercommittee else None,
    }
    return render(request, "WardSachib/print_completion_recommendation.html", context)


from decimal import Decimal, InvalidOperation

from decimal import Decimal, InvalidOperation

from decimal import Decimal, InvalidOperation

def add_final_valuation(request):
    if request.method == "POST":
        try:
            cost_estimated_project_id = request.POST.get("project")
            cost_estimate = CostEstimate.objects.get(id=cost_estimated_project_id)
            project = cost_estimate.project

            # ❌ PREVENT DUPLICATE FINAL PAYMENT
            if hasattr(project, "final_payment"):
                messages.error(
                    request,
                    "यो योजनाको अन्तिम भुक्तानी पहिले नै तयार भइसकेको छ।"
                )
                return redirect("add_final_valuation")

            # ================= DECIMAL FIELDS =================
            final_valuation = Decimal(request.POST.get("totalValuation") or 0)
            office_contribution = Decimal(request.POST.get("officeContribution") or 0)
            user_contribution = Decimal(request.POST.get("usersContribution") or 0)

            application_date_nepali = request.POST.get("application_date")
            application_date = convert_nepali_to_english(application_date_nepali)

            # ================= TAX (पालिकाको कर शीर्षक अनुसार) =================
            tax_deduction, tax_errors = parse_tax_rows(request.POST, {h.code for h in active_heads()})
            if tax_errors:
                for e in tax_errors:
                    messages.error(request, e)
                return redirect(f"{request.path}?project={project.id}")

            paid_before = sum((i.amount for i in project.installments.all()), Decimal("0"))
            if paid_before > office_contribution:
                messages.error(request, f"यस अघि किस्तामा रु. {paid_before:,.2f} दिइसकिएको छ, जुन कार्यालयले बेहोर्ने रकमभन्दा बढी हो।")
                return redirect(f"{request.path}?project={project.id}")
            from projects.outputs import parse_outputs, save_outputs
            out_cat, out_values, out_errors = parse_outputs(request.POST)
            if out_errors:
                for e in out_errors:
                    messages.error(request, e)
                return redirect(f"{request.path}?project={project.id}")
            from .amounts import check_final
            tax_total = sum((Decimal(str(v)) for v in tax_deduction.values()), Decimal("0"))
            amount_errors, amount_warnings = check_final(project, final_valuation, office_contribution,
                                                         user_contribution, tax_total, paid_before)
            if amount_errors:
                for e in amount_errors:
                    messages.error(request, e)
                return redirect(f"{request.path}?project={project.id}")

            if (err := doc_error(request)):
                messages.error(request, err)
                return redirect(f"{request.path}?project={project.id}")
            new_final_payment = FinalPayment(
                project=project,
                application_date=application_date,
                final_evaluation=final_valuation,
                office_contribution=office_contribution,
                user_contribution=user_contribution,
                tax_deduction=tax_deduction,
                status=1,  # Approved
            )
            apply_doc(request, new_final_payment)
            new_final_payment.save()
            log_activity(request, "create", new_final_payment, "अन्तिम भुक्तानी/मूल्याङ्कन")
            if "work_category" in request.POST:
                save_outputs(project, out_cat, out_values, request.user)
            for w in amount_warnings:
                messages.warning(request, w)

            cost_estimate.status = 1
            cost_estimate.save()
            log_activity(request, "update", cost_estimate, "लागत अनुमान", note="अन्तिम भुक्तानी दर्ता भएपछि स्थिति अद्यावधिक भयो")

            messages.success(request, "अन्तिम मूल्याङ्कन सुरक्षित भयो ✅")
            return redirect("view_final_valuation")

        except (InvalidOperation, ValueError) as e:
            messages.error(request, f"Invalid numeric value: {e}")
            return redirect("add_final_valuation")

    cost_estimate = CostEstimate.objects.filter(status=0).select_related("project")
    pre = request.GET.get("project")
    pre_project = Project.objects.filter(id=pre).first() if str(pre or "").isdigit() else None
    return render(
        request,
        "Admin/User/add_final_valuation.html",
        {"cost_estimate": cost_estimate, "tax_heads": active_heads(),
         "out_groups": outputs_catalog(pre_project), "out_category_id": getattr(pre_project, "work_category_id", None),
         **_installment_ctx(request.GET.get("project")),
         # सेटिङमा भएका सबै सक्रिय कर शीर्षक सुरुमै देखिन्छन्; रकम मात्र भर्ने
         "tax_rows": [(h.code, "") for h in active_heads()] or [("", "")],
         "can_add_tax_head": has_perm(request.user, "uc.valuation") or has_perm(request.user, "settings.tax")},
    )


def edit_final_valuation(request, id):
    final_valuation = get_object_or_404(FinalPayment, id=id)

    # Locked once the Tippani has already been printed.
    if final_valuation.tippani_printed:
        messages.error(
            request,
            "टिप्पणी पहिले नै छापिसकेकोले यो अन्तिम मुल्यांकन अब सम्पादन गर्न मिल्दैन।"
        )
        return redirect("view_final_valuation")

    if request.method == "POST":
        try:
            final_valuation.final_evaluation = Decimal(request.POST.get("totalValuation") or 0)
            final_valuation.office_contribution = Decimal(request.POST.get("officeContribution") or 0)
            final_valuation.user_contribution = Decimal(request.POST.get("usersContribution") or 0)

            application_date_nepali = request.POST.get("application_date")
            final_valuation.application_date = convert_nepali_to_english(application_date_nepali)

            allowed = {h.code for h in active_heads()} | set((final_valuation.tax_deduction or {}).keys())
            tax_deduction, tax_errors = parse_tax_rows(request.POST, allowed)
            if tax_errors:
                for e in tax_errors:
                    messages.error(request, e)
                return redirect("edit_final_valuation", id=id)
            final_valuation.tax_deduction = tax_deduction
            if final_valuation.installments_paid > final_valuation.office_contribution:
                messages.error(request, "यस अघि दिइएका किस्ता कार्यालयले बेहोर्ने रकमभन्दा बढी छन्।")
                return redirect("edit_final_valuation", id=id)
            from projects.outputs import parse_outputs, save_outputs
            out_cat, out_values, out_errors = parse_outputs(request.POST)
            if out_errors:
                for e in out_errors:
                    messages.error(request, e)
                return redirect("edit_final_valuation", id=id)
            from .amounts import check_final
            amount_errors, amount_warnings = check_final(
                final_valuation.project, final_valuation.final_evaluation, final_valuation.office_contribution,
                final_valuation.user_contribution, final_valuation.calculate_total_tax(), final_valuation.installments_paid)
            if amount_errors:
                for e in amount_errors:
                    messages.error(request, e)
                return redirect("edit_final_valuation", id=id)
            for w in amount_warnings:
                messages.warning(request, w)

            if (err := doc_error(request)):
                messages.error(request, err)
                return redirect("edit_final_valuation", id=id)
            apply_doc(request, final_valuation)
            final_valuation.save()
            if "work_category" in request.POST:
                save_outputs(final_valuation.project, out_cat, out_values, request.user)
            log_activity(request, "update", final_valuation, "अन्तिम भुक्तानी/मूल्याङ्कन")

            messages.success(request, "अन्तिम मूल्याङ्कन सच्याइयो ✅")
            return redirect("view_final_valuation")

        except (InvalidOperation, ValueError) as e:
            messages.error(request, f"Invalid numeric value: {e}")
            return redirect("edit_final_valuation", id=id)

    application_date_nepali = convert_english_to_nepali(final_valuation.application_date)

    return render(
        request,
        "Admin/User/edit_final_valuation.html",
        {
            "final_valuation": final_valuation,
            "application_date_nepali": application_date_nepali,
            "tax_heads": _heads_with_used(final_valuation.tax_deduction),
            "out_groups": outputs_catalog(final_valuation.project),
            "out_category_id": final_valuation.project.work_category_id,
            **_installment_ctx(final_valuation.project_id),
            "tax_rows": tax_rows(final_valuation.tax_deduction) or [("", "")],
            "can_add_tax_head": has_perm(request.user, "uc.valuation") or has_perm(request.user, "settings.tax"),
        },
    )


def _installment_ctx(project_id):
    """अन्तिम भुक्तानी फारम: यस अघि दिइएका किस्ता (खुद भुक्तानीबाट कट्टी)."""
    from .models import Installment

    if not str(project_id or "").isdigit():
        return {"prev_installments": [], "tax_less": 0}
    items = list(Installment.objects.filter(project_id=project_id))
    return {"prev_installments": items, "tax_less": sum((i.amount for i in items), Decimal("0"))}


def _heads_with_used(tax_deduction):
    """सक्रिय शीर्षक + यो अभिलेखमा प्रयोग भएका (निष्क्रिय भए पनि) — dropdown का लागि."""
    from types import SimpleNamespace

    heads = active_heads()
    have = {h.code for h in heads}
    labels = tax_labels()
    for code in (tax_deduction or {}):
        if code not in have:
            heads.append(SimpleNamespace(code=code, name=labels.get(code, code)))
    return heads



def LOAD_USER_CONTRIBUTION(request):
    project_id = request.GET.get('projectid')
   
    cost_estimate = CostEstimate.objects.filter(id=project_id)

    context = {
        "cost_estimate":cost_estimate
    }
    
    return render(request,"Ajax/user_contribution_dropdown.html",context)





def LOAD_CONTINGENCY(request):
    project_id = request.GET.get('projectid')
    cost_estimate = CostEstimate.objects.filter(id=project_id)
    context = {
        "cost_estimate":cost_estimate
    }
    
    return render(request,"Ajax/contingency_dropdown.html",context)




def LOAD_BUDGET(request):
    project_id = request.GET.get('projectid')
    cost_estimate = CostEstimate.objects.filter(id=project_id)
    context = {
        "cost_estimate":cost_estimate
    }
    
    return render(request,"Ajax/budget_dropdown.html",context)


def VIEW_FINAL_VALUATION(request):
    final_valuation = FinalPayment.objects.all().order_by('-id')
    
    TAX_LABELS = tax_labels()
    context = {
        "final_valuation":final_valuation,
        "tax_labels": TAX_LABELS
    }
    return render(request,"Admin/User/view_final_valuation.html",context)





def PRINT_FINAL_TIPPANI(request,id):
    project = Project.objects.get(id = id)
    usercommittee = UserCommittee.objects.get(project_id = id)
    cost_estimate = CostEstimate.objects.get(project_id = id)
    final_valuation = FinalPayment.objects.get(project_id = id)

    # वडा सिफारिस is optional: the ward may send it through the portal or on paper.
    recommendation = getattr(project, "ward_recommendation", None)

    # Once the Tippani has been printed, the final evaluation is locked
    # against further edits (see edit_final_valuation).
    if not final_valuation.tippani_printed:
        final_valuation.tippani_printed = True
        final_valuation.save()

    application_date_english = final_valuation.application_date
    start_date = usercommittee.start_date
    formation_date = usercommittee.formation_date
    accomplish_date = usercommittee.accomplish_date



    # Convert the start date from English to Nepali
    application_date_nepali = convert_english_to_nepali(application_date_english)
    start_date_nepali = convert_english_to_nepali(start_date)
    formation_date_nepali = convert_english_to_nepali(formation_date)
    accomplish_date_nepali = convert_english_to_nepali(accomplish_date)
    recommendation_date_nepali = convert_english_to_nepali(recommendation.recommendation_date) if recommendation else None

    TAX_LABELS = tax_labels()



    context = {
        "project":project,
        "usercommittee":usercommittee,
        "cost_estimate":cost_estimate,
        "final_valuation":final_valuation,
        "application_date_nepali":application_date_nepali,
        "start_date_nepali":start_date_nepali,
        "formation_date_nepali":formation_date_nepali,
        "accomplish_date_nepali":accomplish_date_nepali,
        "recommendation":recommendation,
        "recommendation_date_nepali":recommendation_date_nepali,
        "tax_labels": TAX_LABELS,
        "installments": list(project.installments.all()),
        "outputs": list(project.outputs.select_related("indicator")),
    }

    return render(request,"Admin/User/print_final_tippani.html",context)




def PRINT_HANDOVER_LETTER(request,id):
    project = Project.objects.get(id = id)

    # काम सम्पन्न सिफारिस: required only for पालिका केन्द्रित projects (checked by
    # workflow.uc_gate in urls.py); वडा प्रत्यायोजित projects do not need it.
    completion_recommendation = getattr(project, "completion_recommendation", None)

    usercommittee = UserCommittee.objects.get(project_id = id)
    cost_estimate = CostEstimate.objects.get(project_id = id)
    final_valuation = FinalPayment.objects.get(project_id = id)
    application_date_english = final_valuation.application_date
    start_date = usercommittee.start_date
    formation_date = usercommittee.formation_date
    accomplish_date = usercommittee.accomplish_date


    # Convert the start date from English to Nepali
    application_date_nepali = convert_english_to_nepali(application_date_english)
    start_date_nepali = convert_english_to_nepali(start_date)
    formation_date_nepali = convert_english_to_nepali(formation_date)
    accomplish_date_nepali = convert_english_to_nepali(accomplish_date)
    
    
    context = {
        "project":project,
        "usercommittee":usercommittee,
        "cost_estimate":cost_estimate,
        "final_valuation":final_valuation,
        "application_date_nepali":application_date_nepali,
        "start_date_nepali":start_date_nepali,
        "formation_date_nepali":formation_date_nepali,
        "accomplish_date_nepali":accomplish_date_nepali,
        "completion_recommendation": completion_recommendation,
        "completion_recommendation_date_nepali": convert_english_to_nepali(
            completion_recommendation.recommendation_date
        ) if completion_recommendation else None,
    }
    
    return render(request,"Admin/User/print_handover.html",context)




def view_usercommittee(request):
    usercommittee = UserCommittee.objects.all().order_by('-id')
    context = {
        "usercommittee":usercommittee
    }
    return render(request,"Admin/User/view_usercommittee.html",context)



def edit_usercommittee(request, id):
    usercommittee = get_object_or_404(UserCommittee, id=id)

    if not committee_access(request, usercommittee.project):
        return redirect("unauthorized")

    context = {
        "usercommittee": usercommittee,
        "formation_date_nepali": convert_english_to_nepali(usercommittee.formation_date),
        "start_date_nepali": convert_english_to_nepali(usercommittee.start_date),
        "accomplish_date_nepali": convert_english_to_nepali(usercommittee.accomplish_date),
        "extended_date_nepali": convert_english_to_nepali(usercommittee.extended_date),
        **roster_ctx(roster_rows(usercommittee) or default_rows(), usercommittee.id),
    }

    return render(
        request,
        "Admin/User/edit_user_committee.html",
        context
    )





import json

def update_usercommittee(request):
    if request.method != "POST":
        return redirect("view_usercommittee")

    usercommittee = get_object_or_404(
        UserCommittee,
        id=request.POST.get("usercommittee_id")
    )

    sachib = get_ward_sachib_profile(request)
    staff_officer = is_planning_or_admin(request)

    if not committee_access(request, usercommittee.project):
        return redirect("unauthorized")

    # ================= BASIC INFO =================
    usercommittee.name = request.POST.get("name")

    # ================= पदाधिकारी तथा सदस्य =================
    rows, errors = parse_roster(request.POST, request.FILES)
    conflict_errors, conflict_warnings = officer_conflict_check(request, rows, usercommittee.id) if not errors else ([], [])
    errors += conflict_errors
    if errors:
        for e in errors:
            messages.error(request, e)
        return render(request, "Admin/User/edit_user_committee.html", {
            "usercommittee": usercommittee,
            "formation_date_nepali": request.POST.get("formation_date", ""),
            "start_date_nepali": request.POST.get("start_date") or convert_english_to_nepali(usercommittee.start_date),
            "accomplish_date_nepali": request.POST.get("accomplish_date") or convert_english_to_nepali(usercommittee.accomplish_date),
            **roster_ctx(rows or default_rows(), usercommittee.id),
        })
    apply_roster(usercommittee, rows)

    # ================= DATES =================
    usercommittee.formation_date = convert_nepali_to_english(
        request.POST.get("formation_date")
    )

    # योजना सुरु/समाप्त मिति — केवल योजना अधिकृत/एडमिनले मात्र सच्याउन
    # सक्ने। वडा सचिवले पेश गरे पनि विद्यमान मिति यथावत राखिन्छ।
    if staff_officer:
        usercommittee.start_date = convert_nepali_to_english(
            request.POST.get("start_date")
        )
        usercommittee.accomplish_date = convert_nepali_to_english(
            request.POST.get("accomplish_date")
        )

    # ================= STATUS =================
    status = request.POST.get("status")
    if status is not None:
        usercommittee.status = int(status)

    usercommittee.save()
    sync_members(usercommittee, rows, request.user)
    log_activity(request, "update", usercommittee, "उपभोक्ता समिति")
    for w in conflict_warnings:
        messages.warning(request, w)

    messages.success(request, "उपभोक्ता समितिको विवरण सफलतापूर्वक अपडेट गरियो।")
    return redirect("ward_project_list") if sachib else redirect("view_usercommittee")




def extend_usercommittee_date(request,id):
    usercommittee = get_object_or_404(UserCommittee, id=id)

    # ================= SAFE DATE CONVERTER =================
    def nepali(date_val):
        return convert_english_to_nepali(date_val) if date_val else ""

    # ================= DATES =================
    formation_date_nepali = nepali(usercommittee.formation_date)
    start_date_nepali = nepali(usercommittee.start_date)
    accomplish_date_nepali = nepali(usercommittee.accomplish_date)

    # If extended_date exists → use it, else fallback to accomplish_date
    base_extended_date = (
        usercommittee.extended_date
        if usercommittee.extended_date
        else usercommittee.accomplish_date
    )
    extended_date_nepali = nepali(base_extended_date)

    # ================= CONTEXT =================
    context = {
        "usercommittee": usercommittee,
        "formation_date_nepali": formation_date_nepali,
        "start_date_nepali": start_date_nepali,
        "accomplish_date_nepali": accomplish_date_nepali,
        "extended_date_nepali": extended_date_nepali,
    }

    return render(
        request,
        "Admin/User/extend_user_committee_date.html",
        context
    )
    
    
    
    
def update_usercommittee_date(request):
    if request.method == "POST":
        usercommittee_id = request.POST.get("usercommittee_id")
        extended_date_nepali = request.POST.get("extended_date")
        # Basic validation
        if not usercommittee_id or not extended_date_nepali:
            messages.error(request, "सबै आवश्यक जानकारी भर्नुहोस्।")
            return redirect("view_usercommittee")
        usercommittee = get_object_or_404(UserCommittee, id=usercommittee_id)
        try:
            # Convert Nepali → English
            extended_date_english = convert_nepali_to_english(extended_date_nepali)

            # Save
            usercommittee.extended_date = extended_date_english
            usercommittee.save()
            log_activity(
                request, "update", usercommittee, "उपभोक्ता समिति",
                note=f"म्याद थप गरियो → {extended_date_nepali}",
            )

            messages.success(
                request,
                "उपभोक्ता समितिको म्याद सफलतापूर्वक अपडेट गरियो।"
            )

            return redirect(
                "print_extended_usercommittee_date",
                id=usercommittee.id
            )

        except Exception as e:
            messages.error(request, f"त्रुटि भयो: {e}")
            return redirect("extend_usercommittee_date", id=usercommittee.id)

    return redirect("view_usercommittee")

import datetime

def PRINT_EXTENDED_LETTER(request,id):
    usercommittee = get_object_or_404(UserCommittee, id=id)
    project = usercommittee.project

    # Cost estimate (optional)
    cost_estimate = getattr(project, "cost_estimate", None)

    # -----------------------------
    # English Dates
    # -----------------------------
    formation_date_en = usercommittee.formation_date
    start_date_en = usercommittee.start_date
    accomplish_date_en = usercommittee.accomplish_date
    extended_date_en = usercommittee.extended_date

    # -----------------------------
    # Convert Dates → Nepali
    # -----------------------------
    formation_date_np = (
        convert_english_to_nepali(formation_date_en)
        if formation_date_en else ""
    )

    start_date_np = (
        convert_english_to_nepali(start_date_en)
        if start_date_en else ""
    )

    accomplish_date_np = (
        convert_english_to_nepali(accomplish_date_en)
        if accomplish_date_en else ""
    )

    extended_date_np = (
        convert_english_to_nepali(extended_date_en)
        if extended_date_en else ""
    )

    # -----------------------------
    # Today Date
    # -----------------------------
    today_en = datetime.date.today()
    today_np = convert_english_to_nepali(today_en)

    # -----------------------------
    # Context
    # -----------------------------
    context = {
        "usercommittee": usercommittee,
        "project": project,
        "cost_estimate": cost_estimate,
        "formation_date_nepali": formation_date_np,
        "start_date_nepali": start_date_np,
        "accomplish_date_nepali": accomplish_date_np,
        "extended_date_nepali": extended_date_np,
        "today_nepali": today_np,
    }

    return render(
        request,
        "Admin/User/print_extended_letter.html",
        context
    )
    
    
def view_usercommittee_payments(request):
    final_payments = FinalPayment.objects.filter(
     
    ).select_related(
        'project',
        'project__user_committee',
        'project__ward',
        'project__fiscalyear',
    ).order_by('-id')

    context = {
        "final_payments": final_payments
    }
    return render(request, "Admin/User/view_usercommittee_payments.html", context)




def download_usercommittee_payments_excel(request):
    # openpyxl (and the numpy it can transitively pull in via
    # openpyxl.compat.numbers) is imported here, not at module level, on
    # purpose: numpy's OpenBLAS backend spins up dozens of native threads on
    # first import. Importing it eagerly at the top of this file meant EVERY
    # page under /UserCommittee/ paid that cost the moment a fresh worker
    # process resolved its first URL — and on a process-limited shared-hosting
    # account, that intermittently exhausted the process quota and broke
    # unrelated pages. Loading it lazily, only for this one Excel-export view
    # that actually needs it, avoids that entirely.
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from django.http import HttpResponse

    final_payments = FinalPayment.objects.filter(
       
    ).select_related(
        'project',
        'project__user_committee',
        'project__ward',
        'project__fiscalyear',
        'project__cost_estimate',
    ).order_by('-id')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Paid Projects"

    headers = [
        "क्र. सं.", "आयोजनाको नाम", "उपभोक्ता समितिको नाम", "उ.स. अध्यक्षको नाम",
        "सम्पर्क नं.", "वडा नं.", "विनियोजित रकम", "सम्झौता रकम",
        "भुक्तानी रकम", "कैफियत",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    thin_border = Border(*(Side(style="thin"),) * 4)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    for idx, i in enumerate(final_payments, start=1):
        committee = getattr(i.project, 'user_committee', None)
        cost_estimate = getattr(i.project, 'cost_estimate', None)

        row = [
            idx,
            i.project.name,
            committee.name if committee else "",
            committee.chairman_name if committee else "",
            committee.chairman_mobile if committee else "",
            i.project.ward.name if i.project.ward else "",
            float(i.project.budget),  # विनियोजित रकम
            float(cost_estimate.total_cost) if cost_estimate else "",  # सम्झौता रकम
            float(i.net_payment),  # भुक्तानी रकम
            "",  # कैफियत
        ]
        ws.append(row)

    for r in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in r:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    # column widths tuned to content type
    widths = [8, 32, 32, 20, 14, 10, 16, 16, 16, 18]
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = width

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="usercommittee_payments.xlsx"'
    wb.save(response)
    return response


def nid_lookup(request):
    """GET ?nid=... -> JSON: NID बाट व्यक्तिको विवरण (API वा पुराना सदस्य)."""
    if not has_perm(request.user, "uc.committee"):
        return JsonResponse({"found": False, "message": "अनुमति छैन।"}, status=403)
    from .conflicts import person_active_posts
    from .models import Person

    out = nid_service.lookup(request.GET.get("nid", ""))
    if out.get("found"):
        p = out["person"]
        person = Person.objects.filter(id=p.get("person_id")).first() if p.get("person_id") else None
        uc = request.GET.get("uc")
        out["active"] = person_active_posts(person, out.get("nid", ""), p.get("citizenship", ""),
                                            int(uc) if str(uc).isdigit() else None)
    return JsonResponse(out)



def tax_heads_page(request):
    """सेटिङ → कर शीर्षक: थप्ने, नाम बदल्ने, क्रम मिलाउने, निष्क्रिय गर्ने."""
    from .models import TaxHead

    if not has_perm(request.user, "settings.tax"):
        return redirect("unauthorized")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            name = (request.POST.get("name") or "").strip()
            if name:
                h = TaxHead.objects.create(name=name[:150], code="tmp", sort=TaxHead.objects.count() + 1)
                h.code = f"tax_{h.id}"
                h.save(update_fields=["code"])
                messages.success(request, f"“{name}” कर शीर्षक थपियो।")
        elif action == "save":
            for h in TaxHead.objects.all():
                name = (request.POST.get(f"name_{h.id}") or "").strip()
                if name:
                    h.name = name[:150]
                try:
                    h.sort = int(request.POST.get(f"sort_{h.id}") or h.sort)
                except ValueError:
                    pass
                h.is_active = bool(request.POST.get(f"active_{h.id}"))
                h.save()
            messages.success(request, "कर शीर्षक सुरक्षित भए।")
        return redirect("tax_heads")
    used = {}
    for fp in FinalPayment.objects.only("tax_deduction"):
        for code in (fp.tax_deduction or {}):
            used[code] = used.get(code, 0) + 1
    heads = [{"h": h, "used": used.get(h.code, 0)} for h in TaxHead.objects.all()]
    return render(request, "Admin/User/tax_heads.html", {"heads": heads})


def tax_head_add_ajax(request):
    """फारमबाटै नयाँ कर शीर्षक (➕). POST name -> JSON {code, name}."""
    from .models import TaxHead

    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    if not (has_perm(request.user, "uc.valuation") or has_perm(request.user, "settings.tax")):
        return JsonResponse({"ok": False, "message": "कर शीर्षक थप्ने अनुमति छैन।"}, status=403)
    name = (request.POST.get("name") or "").strip()[:150]
    if not name:
        return JsonResponse({"ok": False, "message": "कर शीर्षकको नाम लेख्नुहोस्।"}, status=400)
    existing = TaxHead.objects.filter(name__iexact=name).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.save(update_fields=["is_active"])
        return JsonResponse({"ok": True, "code": existing.code, "name": existing.name, "existing": True})
    h = TaxHead.objects.create(name=name, code="tmp", sort=TaxHead.objects.count() + 1)
    h.code = f"tax_{h.id}"
    h.save(update_fields=["code"])
    return JsonResponse({"ok": True, "code": h.code, "name": h.name})
