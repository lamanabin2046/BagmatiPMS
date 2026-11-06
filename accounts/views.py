from django.shortcuts import render
# Create your views here.
from django.shortcuts import render, redirect, HttpResponse

from django.contrib.auth import authenticate, login, logout
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from decimal import Decimal
import json
from projects.models import Project
from biddings.models import SealedBid, AdvancePayment, RunningEvaluation, FinalPayment,Contract
from quatation.models import Quation
from usercommittee.models import UserCommittee
import projects






@never_cache
@ensure_csrf_cookie
def login_view(request):
    """लगइन पेज — ब्राउजरले पुरानो (cache) पेज नदेखाओस्, नत्र पुरानो CSRF token ले 403 आउँछ।"""
    if request.user.is_authenticated:          # Back थिचेर लगइन पेजमा आएमा: आफ्नै गृहपृष्ठ
        from tenants.context_processors import ROLE_HOME

        return redirect(ROLE_HOME.get(str(getattr(request.user, "user_type", "")), "my_work"))
    return render(request,"login.html")


def csrf_failure(request, reason=""):
    """CSRF 403 को सट्टा: लगइन भइसकेको भए गृहपृष्ठ, नभए पेज फेरि खोलेर प्रयास गर्न भन्ने (दुई पटक थिच्दा / पुरानो पेज)।"""
    from django.contrib import messages as msgs

    if request.path.startswith("/Accounts/doLogin") and request.user.is_authenticated:
        return redirect("login")          # माथिको login_view ले गृहपृष्ठमा पठाउँछ
    if request.headers.get("HX-Request"):
        return HttpResponse('<div class="rounded-lg border border-amber-300 bg-amber-50 text-amber-800 text-sm px-3 py-2">'
                            'पेज पुरानो भयो — पेज ताजा (refresh) गरी फेरि प्रयास गर्नुहोस्।</div>', status=403)
    msgs.warning(request, "पेज पुरानो भएकाले फारम पठाउन सकिएन — फेरि प्रयास गर्नुहोस्।")
    back = request.META.get("HTTP_REFERER") or ""
    from django.utils.http import url_has_allowed_host_and_scheme

    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = "/Accounts/login/"
    return redirect(back)


def doLogout(request):
    logout(request)
    return redirect('login')

def doLogin(request):
    if request.method == 'POST':
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')

        from . import security as sec

        ip = sec.client_ip(request)
        mins = sec.lock_status(mobile, ip)
        if mins:
            messages.error(request, f"धेरै पटक गलत पासवर्ड हालिएकाले लगइन {sec._np(mins)} मिनेटका लागि बन्द छ। "
                                    "पासवर्ड बिर्सनुभएको भए “पासवर्ड बिर्सनुभयो?” बाट नयाँ बनाउनुहोस्।")
            return redirect('login')

        # Authenticate using CustomUser (mobile as username)
        user = authenticate(request, mobile=sec.norm_mobile(mobile) or mobile, password=password)

        if user is not None:
            login(request, user)
            sec.clear_failures(mobile)
            sec.log_login(user, True, ip)

            # भूमिकाअनुसार आफ्नै ड्यासबोर्ड (tenants/context_processors.ROLE_HOME)
            from tenants.context_processors import ROLE_HOME

            if user.user_type in ROLE_HOME:
                return redirect(ROLE_HOME[user.user_type])

            else:
                messages.error(request, "User role not recognized.")
                return redirect('login')

        else:
            off = CustomUser.objects.filter(mobile=sec.norm_mobile(mobile) or mobile, is_active=False).first()
            if off is not None and off.check_password(password or ""):
                messages.error(request, "तपाईंको खाता निष्क्रिय गरिएको छ (सरुवा / अवकाश)। थप जानकारीका लागि Admin लाई सम्पर्क गर्नुहोस्।")
                return redirect('login')
            locked, left = sec.record_failure(mobile, ip)
            if locked:
                messages.error(request, f"{sec._np(sec.MAX_FAILS)} पटक गलत पासवर्ड — सुरक्षाका लागि लगइन केही समय बन्द गरियो। "
                                        "पासवर्ड बिर्सनुभएको भए “पासवर्ड बिर्सनुभयो?” प्रयोग गर्नुहोस्।")
            else:
                messages.error(request, "मोबाइल नम्बर वा पासवर्ड गलत छ।" + (f" अझै {sec._np(left)} पटक मात्र प्रयास गर्न सकिन्छ।" if left <= 2 else ""))
            return redirect('login')

    return render(request, 'login.html')


from datetime import date, timedelta
from decimal import Decimal
from datetime import date, timedelta

from django.db.models import Sum
from django.shortcuts import render

from projects.models import Project
from decimal import Decimal
from usercommittee.models import UserCommittee
def ADMIN_HOME(request):
    """पुरानो Admin ड्यासबोर्ड — अब मुख्य ड्यासबोर्डमा गाभिएको (पुराना लिङ्क / bookmark का लागि redirect)."""
    return redirect("dashboard")


from .models import ( CustomUser, Admin, Cao, PlanningOfficer,
    Engineer, WadaStaff, WardSachib, WardEngineer, PalikaEngineer, Ward
, WardChairperson, AccountOfficer)
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction

def add_staff(request):
    wards = Ward.objects.all()

    if request.method == "POST":
        try:
            with transaction.atomic():

                mobile = request.POST.get("mobile")
                password = request.POST.get("password")
                name = request.POST.get("name")
                user_type = request.POST.get("user_type")
                selected_wards = request.POST.getlist("wards")

                # ---------------------------
                # Create User
                # ---------------------------
                user = CustomUser.objects.create_user(
                    mobile=mobile,
                    password=password,
                    user_type=user_type
                )

                # ---------------------------
                # Create Staff by Role
                # ---------------------------
                if user_type == "1":   # ADMIN
                    Admin.objects.create(
                        admin=user,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "2":  # CAO
                    Cao.objects.create(
                        admin=user,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "3":  # PLANNING OFFICER
                    PlanningOfficer.objects.create(
                        admin=user,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "4":  # ENGINEER
                    Engineer.objects.create(
                        admin=user,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "5":  # WARD STAFF
                    staff = WadaStaff.objects.create(
                        admin=user,
                        name=name,
                        mobile=mobile
                    )
                    staff.wards.set(selected_wards)

                elif user_type == "6":  # WARD SACHIB
                    sachib_ward = request.POST.get("sachib_ward")
                    if not sachib_ward:
                        raise ValueError("वडा सचिवको लागि वडा छान्नु आवश्यक छ।")
                    WardSachib.objects.create(
                        admin=user,
                        ward_id=sachib_ward,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "7":  # WARD ENGINEER
                    engineer_ward = request.POST.get("engineer_ward")
                    if not engineer_ward:
                        raise ValueError("वडा इन्जिनियरको लागि वडा छान्नु आवश्यक छ।")
                    WardEngineer.objects.create(
                        admin=user,
                        ward_id=engineer_ward,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "8":  # PALIKA ENGINEER
                    PalikaEngineer.objects.create(
                        admin=user,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "9":  # WARD CHAIRPERSON (वडा अध्यक्ष)
                    chair_ward = request.POST.get("sachib_ward")
                    if not chair_ward:
                        raise ValueError("वडा अध्यक्षको लागि वडा छान्नु आवश्यक छ।")
                    WardChairperson.objects.create(
                        admin=user,
                        ward_id=chair_ward,
                        name=name,
                        mobile=mobile
                    )

                elif user_type == "10":  # ACCOUNT OFFICER (लेखा अधिकृत)
                    AccountOfficer.objects.create(admin=user, name=name, mobile=mobile)

                messages.success(request, f"कर्मचारी “{name}” सफलतापूर्वक थपियो।")
                return redirect("manage_staff")

        except Exception as e:
            messages.error(request, f"त्रुटि भयो: {e}")

    return render(request, "Admin/Accounts/add_staff.html", {
        "wards": wards
    })


# Maps CustomUser.user_type -> the reverse OneToOne accessor name for that
# role's profile record (e.g. user.wardsachib), so manage_staff/reset_staff_password
# can look up a staff member's display name/status without a big if/elif chain.
ROLE_PROFILE_ATTR = {
    "1": "admin",
    "2": "cao",
    "3": "planningofficer",
    "9": "wardchairperson",
    "4": "engineer",
    "5": "wadastaff",
    "6": "wardsachib",
    "7": "wardengineer",
    "8": "palikaengineer",
    "10": "accountofficer",
}


def _staff_profile(user):
    """Returns (name, status) for a CustomUser by looking up its role-specific
    profile record. Falls back to the mobile number / "—" if the profile is
    somehow missing (shouldn't normally happen, but add_staff wraps creation
    in a transaction so it's defensive rather than load-bearing)."""
    attr = ROLE_PROFILE_ATTR.get(user.user_type)
    profile = getattr(user, attr, None) if attr else None
    if profile is None:
        return user.mobile, "—"
    return profile.name, profile.status


def manage_staff(request):
    """कर्मचारी व्यवस्थापन — Admin-only list of every staff account, with a
    पासवर्ड रिसेट action per row. This project has no email on CustomUser and
    no SMS gateway configured, so "forgot password" is handled by the Admin
    resetting the account directly here rather than a self-service flow."""
    if not (request.user.is_authenticated and getattr(request.user, "user_type", None) == "1"):
        return redirect("unauthorized")

    users = CustomUser.objects.exclude(pk=request.user.pk).order_by("-is_active", "user_type", "mobile")
    role_label_map = dict(CustomUser.USER_CHOICES)

    staff_rows = []
    for user in users:
        name, status = _staff_profile(user)
        try:
            role_label = role_label_map.get(int(user.user_type), user.user_type)
        except (TypeError, ValueError):
            role_label = user.user_type
        staff_rows.append({
            "id": user.pk,
            "name": name,
            "mobile": user.mobile,
            "role": role_label,
            "status": status,
            "is_active": user.is_active,
        })

    return render(request, "Admin/Accounts/manage_staff.html", {
        "staff_rows": staff_rows,
    })


def reset_staff_password(request, user_id):
    """Admin sets a new password directly for a staff member who forgot
    theirs. POST-only; no old password required since the whole point is
    that the user can no longer log in to provide one."""
    if not (request.user.is_authenticated and getattr(request.user, "user_type", None) == "1"):
        return redirect("unauthorized")

    target_user = CustomUser.objects.filter(pk=user_id).first()
    if target_user is None:
        messages.error(request, "प्रयोगकर्ता फेला परेन।")
        return redirect("manage_staff")

    if target_user.pk == request.user.pk:
        messages.error(request, "आफ्नै पासवर्ड यहाँबाट रिसेट गर्न मिल्दैन।")
        return redirect("manage_staff")

    if request.method == "POST":
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if len(new_password) < 4:
            messages.error(request, "पासवर्ड कम्तिमा ४ अक्षरको हुनुपर्छ।")
        elif new_password != confirm_password:
            messages.error(request, "पासवर्ड र पासवर्ड पुष्टि मिलेन।")
        else:
            target_user.set_password(new_password)
            target_user.save(update_fields=["password"])
            from .security import clear_failures
            clear_failures(target_user.mobile)

            try:
                from usercommittee.models import ActivityLog
                name, _status = _staff_profile(target_user)
                ActivityLog.objects.create(
                    user=request.user,
                    action="update",
                    model_name="प्रयोगकर्ता (पासवर्ड रिसेट)",
                    object_id=target_user.pk,
                    object_repr=f"{name} ({target_user.mobile})",
                    note="Admin द्वारा पासवर्ड रिसेट गरियो",
                )
            except Exception:
                pass

            messages.success(request, f"{target_user.mobile} को पासवर्ड सफलतापूर्वक रिसेट भयो।")

    return redirect("manage_staff")


def toggle_staff_active(request, user_id):
    """कर्मचारी निष्क्रिय / सक्रिय — सरुवा, अवकाश आदिमा। खाता मेटिँदैन: पुराना
    स्वीकृति, पत्र र अभिलेखमा नाम रहिरहन्छ, तर लगइन तुरुन्तै बन्द हुन्छ
    (Django ले निष्क्रिय प्रयोगकर्ताको खुला session पनि अर्को अनुरोधमै रद्द गर्छ)।"""
    if not (request.user.is_authenticated and getattr(request.user, "user_type", None) == "1"):
        return redirect("unauthorized")
    if request.method != "POST":
        return redirect("manage_staff")

    target_user = CustomUser.objects.filter(pk=user_id).first()
    if target_user is None:
        messages.error(request, "प्रयोगकर्ता फेला परेन।")
        return redirect("manage_staff")
    if target_user.pk == request.user.pk:
        messages.error(request, "आफ्नै खाता निष्क्रिय गर्न मिल्दैन।")
        return redirect("manage_staff")

    activate = request.POST.get("action") == "activate"
    if not activate and target_user.user_type == "1" and not CustomUser.objects.filter(
            user_type="1", is_active=True).exclude(pk=target_user.pk).exists():
        messages.error(request, "अन्तिम सक्रिय Admin लाई निष्क्रिय गर्न मिल्दैन।")
        return redirect("manage_staff")

    target_user.is_active = activate
    target_user.save(update_fields=["is_active"])
    attr = ROLE_PROFILE_ATTR.get(target_user.user_type)
    profile = getattr(target_user, attr, None) if attr else None
    if profile is not None and hasattr(profile, "status"):
        profile.status = "Active" if activate else "Inactive"
        profile.save(update_fields=["status"])

    name, _status = _staff_profile(target_user)
    reason = (request.POST.get("reason") or "").strip()[:200]
    try:
        from usercommittee.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            action="update",
            model_name="प्रयोगकर्ता (" + ("सक्रिय" if activate else "निष्क्रिय") + ")",
            object_id=target_user.pk,
            object_repr=f"{name} ({target_user.mobile})",
            note=("Admin द्वारा खाता सक्रिय गरियो" if activate else "Admin द्वारा खाता निष्क्रिय गरियो")
                 + (f" — {reason}" if reason else ""),
        )
    except Exception:
        pass

    if activate:
        messages.success(request, f"{name} ({target_user.mobile}) को खाता फेरि सक्रिय भयो।")
    else:
        msg = f"{name} ({target_user.mobile}) को खाता निष्क्रिय भयो — अब लगइन गर्न मिल्दैन।"
        if target_user.user_type == "2":
            msg += " नयाँ प्रमुख प्रशासकीय अधिकृतको नाम कार्यालय सेटिङमा पनि बदल्नुहोस् (पत्रमा त्यहीँबाट छापिन्छ)।"
        messages.success(request, msg)
    return redirect("manage_staff")


def engineer_home(request):
    context = {
        "total_projects": Project.objects.count(),
        "estimated_projects": Project.objects.filter(cost_estimate__isnull=False).count(),
        "contracted_projects": SealedBid.objects.filter(status=3).count(),
        "completed_projects": Project.objects.filter(status=2).count(),

        "last_user_committees": Project.objects.order_by("-id")[:5],
        "last_bidding_projects": SealedBid.objects.order_by("-id")[:3],
        "last_quotation_projects": Quation.objects.order_by("-id")[:3],
    }    
    return render(request, "Engineer/home.html", context)




def view_projects_engineer(request):
    projects = Project.objects.all()
    return render(request, "Engineer/view_projects_engineer.html", {
        "projects": projects
    })
def view_usercommittee_engineer(request):
    user_committees = UserCommittee.objects.all()
    return render(request, "Engineer/view_usercommittee_engineer.html", {
        "user_committees": user_committees
    })
    
    
    
from biddings.models import AdvanceBankGuarantee

def view_advance_bank_guarantees_engineer(request):
    guarantees = AdvanceBankGuarantee.objects.select_related(
        "advance_payment__contract__sealed_bid__project"
    )

    return render(
        request,
        "Engineer/view_advance_bank_guarantees.html",
        {
            "guarantees": guarantees
        }
    )
from biddings.models import PerformanceBondIssued

def view_performance_bank_guarantees_engineer(request):
    bonds = PerformanceBondIssued.objects.select_related(
        "contract__sealed_bid__project"
    )

    return render(
        request,
        "Engineer/view_performance_bank_guarantees.html",
        {
            "bonds": bonds
        }
    )


# ===================== WARD SACHIB =====================
from usercommittee.models import WardRecommendation


def unauthorized_view(request):
    return render(request, "unauthorized.html")


def get_ward_sachib_profile(request):
    """Return the WardSachib profile for the logged-in user, or None
    if the user isn't authenticated as a Ward Sachib."""
    if not request.user.is_authenticated or request.user.user_type != '6':
        return None
    return WardSachib.objects.select_related("ward").filter(admin=request.user).first()


def ward_sachib_home(request):
    sachib = get_ward_sachib_profile(request)
    if not sachib:
        return redirect('unauthorized')

    # Projects in this Sachib's ward whose उपभोक्ता समिति cost estimate is
    # ready, i.e. eligible for a सिफारिस recommendation.
    projects = Project.objects.filter(
        ward=sachib.ward,
        cost_estimate__isnull=False,
    ).select_related("cost_estimate", "user_committee", "ward_recommendation")

    pending_count = projects.filter(ward_recommendation__isnull=True).count()
    issued_count = projects.filter(ward_recommendation__isnull=False).count()

    # Projects in this ward that don't have a उपभोक्ता समिति filled in yet —
    # this is the Sachib's starting point for a new project.
    committee_pending_count = Project.objects.filter(
        ward=sachib.ward, user_committee__isnull=True
    ).count()

    # Projects in this ward whose अन्तिम मूल्याङ्कन is ready but whose
    # काम सम्पन्न सिफारिस (completion recommendation) hasn't been issued yet.
    completion_pending_count = Project.objects.filter(
        ward=sachib.ward, final_payment__isnull=False, completion_recommendation__isnull=True
    ).count()

    # ============================================================
    # DASHBOARD CHARTS
    # ============================================================
    ward_projects = Project.objects.filter(ward=sachib.ward)
    total_ward_projects = ward_projects.count()

    # ---- 1) उपभोक्ता समिति स्थिति (donut): गठन भयो vs बाँकी ----
    committee_done_count = total_ward_projects - committee_pending_count

    # ---- 2) योजना प्रगति चरण अनुसार (bar): six mutually-exclusive stages,
    # each project counted exactly once, at the stage it's currently
    # waiting on — mirrors the sequence every project moves through:
    # समिति → लागत अनुमान → सिफारिस → भुक्तानी → सम्पन्न सिफारिस → सम्पन्न.
    stage_committee_pending = committee_pending_count
    stage_cost_estimate_pending = ward_projects.filter(
        user_committee__isnull=False, cost_estimate__isnull=True
    ).count()
    stage_recommendation_pending = ward_projects.filter(
        cost_estimate__isnull=False, ward_recommendation__isnull=True
    ).count()
    stage_payment_pending = ward_projects.filter(
        ward_recommendation__isnull=False, final_payment__isnull=True
    ).count()
    stage_completion_recommendation_pending = ward_projects.filter(
        final_payment__isnull=False, completion_recommendation__isnull=True
    ).count()
    stage_completed = ward_projects.filter(completion_recommendation__isnull=False).count()

    pipeline_labels = [
        "समिति बाँकी", "लागत अनुमान बाँकी", "सिफारिस बाँकी",
        "भुक्तानी बाँकी", "सम्पन्न सिफारिस बाँकी", "सम्पन्न",
    ]
    pipeline_counts = [
        stage_committee_pending, stage_cost_estimate_pending, stage_recommendation_pending,
        stage_payment_pending, stage_completion_recommendation_pending, stage_completed,
    ]

    # ---- 3) कुल भुक्तानी (total paid) + बजेट उपयोग (fund utilization) ----
    total_paid = ward_projects.filter(final_payment__isnull=False).aggregate(
        total=Sum("final_payment__office_contribution")
    )["total"] or Decimal("0")
    # Project.budget is a FloatField, so the aggregate comes back as a float —
    # route it through str() before Decimal() the same way ADMIN_HOME does,
    # since Decimal(float) directly would also pick up float binary noise.
    total_ward_budget_raw = ward_projects.aggregate(total=Sum("budget"))["total"] or 0
    total_ward_budget = Decimal(str(total_ward_budget_raw))
    utilization_percent = (
        (total_paid / total_ward_budget) * Decimal("100")
        if total_ward_budget > 0 else Decimal("0")
    )

    context = {
        "sachib": sachib,
        "total_count": projects.count(),
        "pending_count": pending_count,
        "issued_count": issued_count,
        "committee_pending_count": committee_pending_count,
        "completion_pending_count": completion_pending_count,
        "recent_projects": projects.order_by("-id")[:5],

        # charts
        "total_ward_projects": total_ward_projects,
        "committee_done_count": committee_done_count,
        "pipeline_labels_json": json.dumps(pipeline_labels),
        "pipeline_counts_json": json.dumps(pipeline_counts),
        "total_paid": total_paid,
        "total_ward_budget": total_ward_budget,
        "utilization_percent": utilization_percent,
    }
    return render(request, "WardSachib/home.html", context)


# ===================== PLANNING OFFICER =====================

def planning_home(request):
    """Landing dashboard for the PLANNING OFFICER role. Planning
    officers (like Admin) have full, unrestricted access to उपभोक्ता
    समिति creation/editing — including the योजना सुरु/समाप्त मिति
    fields that Ward Sachib users are not allowed to set."""
    if not request.user.is_authenticated or request.user.user_type != '3':
        return redirect('unauthorized')
    return redirect('planning_dash')  # नयाँ योजना अधिकृत ड्यासबोर्ड

    from usercommittee.models import UserCommittee as _UserCommittee, CostEstimate as _CostEstimate
    from usercommittee.views import usercommittee_deadline_alerts

    context = {
        "committee_pending_count": Project.objects.filter(user_committee__isnull=True).count(),
        "cost_estimate_pending_count": Project.objects.filter(
            user_committee__isnull=False, cost_estimate__isnull=True
        ).count(),
        "total_committees": _UserCommittee.objects.count(),
    }
    context.update(usercommittee_deadline_alerts(limit=5, soon_days=30))
    return render(request, "Planning/home.html", context)


# ===================== WARD ENGINEER =====================

def get_ward_engineer_profile(request):
    """Return the WardEngineer profile for the logged-in user, or None
    if the user isn't authenticated as a Ward Engineer."""
    if not request.user.is_authenticated or request.user.user_type != '7':
        return None
    return WardEngineer.objects.select_related("ward").filter(admin=request.user).first()


def ward_engineer_home(request):
    """Landing dashboard for the WARD ENGINEER role. A ward engineer
    sees only the projects of their own ward and enters लागत अनुमान
    (cost estimate) details for them — same projects a Ward Sachib
    hands over after उपभोक्ता समिति formation (status=1)."""
    engineer = get_ward_engineer_profile(request)
    if not engineer:
        return redirect('unauthorized')

    from usercommittee.models import CostEstimate as _CostEstimate
    from projects.models import ProjectTimeline as _ProjectTimeline

    ward_projects = Project.objects.filter(ward=engineer.ward)
    total_ward_projects = ward_projects.count()

    estimate_pending_count = ward_projects.filter(
        user_committee__isnull=False, cost_estimate__isnull=True
    ).count()
    estimate_done_count = ward_projects.filter(cost_estimate__isnull=False).count()
    committee_not_formed_count = ward_projects.filter(user_committee__isnull=True).count()

    # ============================================================
    # DASHBOARD CHARTS
    # ============================================================

    # ---- 1) लागत अनुमान स्थिति (donut): three mutually-exclusive buckets
    # that sum to total_ward_projects — भयो / बाँकी / समिति गठन बाँकी.
    # (estimate_done_count, estimate_pending_count, committee_not_formed_count
    # computed above already cover this.)

    # ---- 2) फोटो टाइमलाइन वडा भर (bar): सुरु अघि / भइरहेको / सम्पन्न भएपछि,
    # counted across every project in this ward, regardless of who
    # uploaded them.
    photo_counts_by_stage = _ProjectTimeline.objects.filter(
        project__ward=engineer.ward
    ).values("stage").annotate(count=Count("id"))
    photo_count_map = {row["stage"]: row["count"] for row in photo_counts_by_stage}

    photo_stage_labels = ["सुरु अघि", "भइरहेको बेला", "सम्पन्न भएपछि"]
    photo_stage_counts = [
        photo_count_map.get(_ProjectTimeline.STAGE_BEFORE, 0),
        photo_count_map.get(_ProjectTimeline.STAGE_DURING, 0),
        photo_count_map.get(_ProjectTimeline.STAGE_AFTER, 0),
    ]

    # ---- 3) कुल लागत अनुमान रकम + बजेट दायरा ----
    total_estimated = ward_projects.filter(cost_estimate__isnull=False).aggregate(
        total=Sum("cost_estimate__total_cost")
    )["total"] or Decimal("0")
    # Project.budget is a FloatField, so the aggregate comes back as a float —
    # route it through str() before Decimal(), same fix as ward_sachib_home.
    total_ward_budget_raw = ward_projects.aggregate(total=Sum("budget"))["total"] or 0
    total_ward_budget = Decimal(str(total_ward_budget_raw))
    estimate_utilization_percent = (
        (total_estimated / total_ward_budget) * Decimal("100")
        if total_ward_budget > 0 else Decimal("0")
    )

    context = {
        "engineer": engineer,
        "total_count": total_ward_projects,
        "estimate_pending_count": estimate_pending_count,
        "estimate_done_count": estimate_done_count,
        "committee_not_formed_count": committee_not_formed_count,
        "recent_projects": ward_projects.order_by("-id")[:5],

        # charts
        "photo_stage_labels_json": json.dumps(photo_stage_labels),
        "photo_stage_counts_json": json.dumps(photo_stage_counts),
        "total_estimated": total_estimated,
        "total_ward_budget": total_ward_budget,
        "estimate_utilization_percent": estimate_utilization_percent,
    }
    return render(request, "WardEngineer/home.html", context)


def get_palika_engineer_profile(request):
    """Return the PalikaEngineer profile for the logged-in user, or None
    if the user isn't authenticated as a Palika Engineer. Unlike
    get_ward_engineer_profile, this role isn't scoped to any one ward."""
    if not request.user.is_authenticated or request.user.user_type != '8':
        return None
    return PalikaEngineer.objects.filter(admin=request.user).first()


def palika_engineer_home(request):
    """Landing dashboard for the PALIKA ENGINEER role — the municipality-
    wide counterpart to ward_engineer_home. A Palika Engineer sees every
    project across every ward (no ward filter) and enters/edits लागत
    अनुमान (cost estimate) details for any of them."""
    palika_engineer = get_palika_engineer_profile(request)
    if not palika_engineer:
        return redirect('unauthorized')

    from usercommittee.models import CostEstimate as _CostEstimate
    from projects.models import ProjectTimeline as _ProjectTimeline

    all_projects = Project.objects.select_related("ward")
    total_projects = all_projects.count()

    estimate_pending_count = all_projects.filter(
        user_committee__isnull=False, cost_estimate__isnull=True
    ).count()
    estimate_done_count = all_projects.filter(cost_estimate__isnull=False).count()
    committee_not_formed_count = all_projects.filter(user_committee__isnull=True).count()

    # ============================================================
    # DASHBOARD CHARTS (municipality-wide — no ward filter)
    # ============================================================

    # ---- 1) लागत अनुमान स्थिति (donut): भयो / बाँकी / समिति गठन बाँकी.
    # (counts computed above already cover this.)

    # ---- 2) फोटो टाइमलाइन सम्पूर्ण पालिका भर (bar) ----
    photo_counts_by_stage = _ProjectTimeline.objects.values("stage").annotate(count=Count("id"))
    photo_count_map = {row["stage"]: row["count"] for row in photo_counts_by_stage}

    photo_stage_labels = ["सुरु अघि", "भइरहेको बेला", "सम्पन्न भएपछि"]
    photo_stage_counts = [
        photo_count_map.get(_ProjectTimeline.STAGE_BEFORE, 0),
        photo_count_map.get(_ProjectTimeline.STAGE_DURING, 0),
        photo_count_map.get(_ProjectTimeline.STAGE_AFTER, 0),
    ]

    # ---- 3) कुल लागत अनुमान रकम + बजेट दायरा ----
    total_estimated = all_projects.filter(cost_estimate__isnull=False).aggregate(
        total=Sum("cost_estimate__total_cost")
    )["total"] or Decimal("0")
    total_budget_raw = all_projects.aggregate(total=Sum("budget"))["total"] or 0
    total_budget = Decimal(str(total_budget_raw))
    estimate_utilization_percent = (
        (total_estimated / total_budget) * Decimal("100")
        if total_budget > 0 else Decimal("0")
    )

    from usercommittee.views import usercommittee_deadline_alerts

    context = {
        "palika_engineer": palika_engineer,
        "total_count": total_projects,
        "estimate_pending_count": estimate_pending_count,
        "estimate_done_count": estimate_done_count,
        "committee_not_formed_count": committee_not_formed_count,
        "recent_projects": all_projects.order_by("-id")[:5],

        # charts
        "photo_stage_labels_json": json.dumps(photo_stage_labels),
        "photo_stage_counts_json": json.dumps(photo_stage_counts),
        "total_estimated": total_estimated,
        "total_ward_budget": total_budget,
        "estimate_utilization_percent": estimate_utilization_percent,
    }
    context.update(usercommittee_deadline_alerts(limit=5, soon_days=30))
    return render(request, "PalikaEngineer/home.html", context)