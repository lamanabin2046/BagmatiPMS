"""उपभोक्ता समिति कार्यप्रवाह (workflow tracker) pages."""
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
import mimetypes

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import CustomUser, UserPermission, Ward, WadaStaff, WardChairperson, WardEngineer, WardSachib
from accounts.permissions import GRANTABLE, ROLE_LABEL, clear_cache, has_perm, user_perms
from projects.models import FiscalYear, project_uc_mode

from .models import Person, ProjectCompletionRecommendation, UCApproval, WardRecommendation
from .roster import DOC_KINDS, gender_summary, roster_rows
from .workflow import (COLUMNS, add_next, MODE_LABELS, approver_identity, bs_date, can_approve, open_keys, project_workflow,
                       row_cells, with_next, workflow_queryset)

ALLOWED = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
UPLOAD_TYPES = (".pdf", ".jpg", ".jpeg", ".png")
UPLOAD_MAX_MB = 10


def _user_wards(user):
    """Wards a ward-level user may see; None means all wards."""
    t = user.user_type
    if t == "6":
        p = WardSachib.objects.filter(admin=user).first()
        return [p.ward_id] if p else []
    if t == "7":
        p = WardEngineer.objects.filter(admin=user).first()
        return [p.ward_id] if p else []
    if t == "9":
        p = WardChairperson.objects.filter(admin=user).first()
        return [p.ward_id] if p else []
    if t == "5":
        p = WadaStaff.objects.filter(admin=user).first()
        return list(p.wards.values_list("id", flat=True)) if p else []
    return None


def _scoped(request):
    qs = workflow_queryset()
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    return qs, wards


def _return_to(request):
    """The workflow page the request came from (HTMX sends it), with its filters."""
    current = urlparse(request.headers.get("HX-Current-URL", ""))
    if current.path:
        return current.path + ("?" + current.query if current.query else "")
    return reverse("usercommittee_workflow")


def with_open(url, project_id):
    """Workflow URL + ?open=<project_id> (फर्केपछि त्यही योजनाको panel आफैँ खुल्छ)."""
    from urllib.parse import parse_qsl, urlencode

    parts = urlparse(url)
    if parts.path.rstrip("/") != reverse("usercommittee_workflow").rstrip("/"):
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "open"]
    query.append(("open", str(project_id)))
    return parts.path + "?" + urlencode(query)


def _strip_open(url):
    from urllib.parse import parse_qsl, urlencode

    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "open"]
    return parts.path + ("?" + urlencode(query) if query else "")


def _back_to_page(request, project_id=None):
    """After an HTMX form in the panel succeeds: reload the workflow page (shows the message)."""
    response = HttpResponse(status=204)
    url = _return_to(request)
    response["HX-Redirect"] = with_open(url, project_id) if project_id else url
    return response


@login_required
def workflow_list(request):
    if request.user.user_type not in ALLOWED:
        return redirect("unauthorized")
    qs, wards = _scoped(request)

    q = request.GET.get("q", "").strip()
    ward = request.GET.get("ward", "")
    from projects.fiscal import default_fy_param

    fy = default_fy_param(request)   # पूर्वनिर्धारित: चालु आ.व.
    stage = request.GET.get("stage", "")
    mode_f = request.GET.get("mode", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(user_committee__name__icontains=q) | Q(address__icontains=q))
    if ward:
        qs = qs.filter(ward_id=ward)
    if fy:
        qs = qs.filter(fiscalyear_id=fy)

    rows = []
    counts = {"all": 0, "running": 0, "overdue": 0, "completed": 0, "to_approve": 0}
    for project in qs:
        steps, summary = project_workflow(project, request.user.user_type, request.user)
        if mode_f and summary["mode"] != mode_f:
            continue
        counts["all"] += 1
        if summary["completed"]:
            counts["completed"] += 1
        else:
            counts["running"] += 1
        if summary["overdue"]:
            counts["overdue"] += 1
        waiting_me = summary["current_key"] == "approval" and can_approve(request.user, project, summary["mode"])
        if waiting_me:
            counts["to_approve"] += 1
        if stage == "running" and summary["completed"]:
            continue
        if stage == "completed" and not summary["completed"]:
            continue
        if stage == "overdue" and not summary["overdue"]:
            continue
        if stage == "to_approve" and not waiting_me:
            continue
        if stage and stage not in ("running", "completed", "overdue", "to_approve") and stage not in open_keys(steps, summary):
            continue   # समिति बाँकी हुँदा "लागत अनुमान" छान्दा पनि देखिने (जुनसुकै क्रम)
        rows.append({"project": project, "steps": steps, "cells": row_cells(steps), "summary": summary,
                     "waiting_me": waiting_me})

    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    per_page = per_page if per_page in (10, 25, 50, 100) else 25
    page = Paginator(rows, per_page).get_page(request.GET.get("page"))
    page_rows = list(page.object_list)

    # ?open=<id>: फारम सुरक्षित गरेर फर्केपछि त्यही योजनाको panel आफैँ खोल्ने (अर्को पेज/फिल्टरमा भए पनि)
    open_id = request.GET.get("open", "")
    open_id = int(open_id) if open_id.isdigit() else None
    if open_id and not any(r["project"].id == open_id for r in page_rows):
        row = next((r for r in rows if r["project"].id == open_id), None)
        if row is None:
            base, _w = _scoped(request)
            project = base.filter(id=open_id).first()
            if project is not None:
                steps, summary = project_workflow(project, request.user.user_type, request.user)
                row = {"project": project, "steps": steps, "cells": row_cells(steps), "summary": summary,
                       "waiting_me": summary["current_key"] == "approval"
                                     and can_approve(request.user, project, summary["mode"])}
        if row is not None:
            page_rows.insert(0, row)
        else:
            open_id = None

    keep = request.GET.copy()
    keep.pop("page", None)
    keep.pop("open", None)
    tenant = getattr(request, "tenant", None)
    ctx = {
        "page": page,
        "rows": page_rows,
        "open_id": open_id,
        "columns": COLUMNS,
        "counts": counts,
        "wards": Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all(),
        "fiscal_years": FiscalYear.objects.all().order_by("-name"),
        "f": {"q": q, "ward": ward, "fiscalyear": fy, "stage": stage, "mode": mode_f, "per_page": per_page},
        "keep_qs": keep.urlencode(),
        "return_to": _strip_open(request.get_full_path()),
        "palika_mode": getattr(tenant, "uc_mode", "municipal"),
        "mode_labels": MODE_LABELS,
        "is_approver": bool(user_perms(request.user) & {"uc.approve", "uc.approve_ward"}),
    }
    return render(request, "Admin/User/workflow.html", ctx)


@login_required
def workflow_detail(request, project_id):
    """HTMX partial: the step-by-step panel for one project."""
    if request.user.user_type not in ALLOWED:
        return redirect("unauthorized")
    qs, _ = _scoped(request)
    project = get_object_or_404(qs, id=project_id)
    steps, summary = project_workflow(project, request.user.user_type, request.user)
    from projects.fiscal import lock_steps, old_message

    fy_locked = lock_steps(project, steps + [summary["progress"]])
    with_next(steps + [{"actions": summary["progress"]["actions"]}], with_open(_return_to(request), project.id))
    if summary.get("installments"):
        summary["installments"]["url"] = add_next(summary["installments"]["url"], with_open(_return_to(request), project.id))
    focus = request.GET.get("step")
    return render(request, "Admin/User/_workflow_detail.html", {
        "project": project, "steps": steps, "summary": summary,
        "fy_locked": fy_locked, "fy_lock_msg": old_message(project) if fy_locked else "",
        "focus": int(focus) if focus and focus.isdigit() else summary["current"],
    })


# ---------------------------------------------------------------- रुजु / स्वीकृत (modal)
def _doc_rows(committee):
    """समितिका सदस्य, हरेकका कागजातको link (सुरक्षित view बाट) सहित."""
    rows = roster_rows(committee) if committee else []
    for r in rows:
        p = r.get("person")
        r["doc_list"] = []
        for kind, label in DOC_KINDS:
            f = p.doc(kind) if p else None
            r["doc_list"].append({
                "kind": kind, "label": label,
                "url": reverse("uc_person_doc", args=[p.id, kind]) if f else "",
                "pdf": bool(f and f.name.lower().endswith(".pdf")),
            })
    return rows


def _review_ctx(request, project, mode):
    committee = getattr(project, "user_committee", None)
    rows = _doc_rows(committee)
    problems = []
    if hasattr(project, "uc_approval"):
        problems.append("यो योजना पहिले नै स्वीकृत भइसकेको छ।")
    if committee is None:
        problems.append("उपभोक्ता समिति गठन भएको छैन।")
    if not hasattr(project, "cost_estimate"):
        problems.append("लागत अनुमान बाँकी छ।")
    if mode == "municipal" and not hasattr(project, "ward_recommendation"):
        problems.append("वडा सिफारिस (पोर्टल वा अपलोड) बाँकी छ।")
    missing = [r for r in rows if r["missing"]]
    if missing:
        problems.append(f"{len(missing)} जना सदस्यका कागजात नपुगेका छन् (तल रातो चिन्ह)।")
    from .amounts import estimate_summary
    from .conflicts import is_blocking, roster_conflicts
    conflicts = roster_conflicts(rows, committee.id) if committee else []
    conflict_block = bool(conflicts) and is_blocking()
    est_sum = estimate_summary(getattr(project, "cost_estimate", None))
    if est_sum and not est_sum["ok"]:
        from .amounts import pct_str
        problems.append(f"उपभोक्ता अंशदान {pct_str(est_sum['pct'])}% मात्र — कम्तीमा {pct_str(est_sum['need'])}% चाहिन्छ (लागत अनुमान सच्याउनुहोस्)।")
    if conflict_block:
        problems.append(f"{len(conflicts)} जना पदाधिकारी अर्को सक्रिय समितिमा पनि पदाधिकारी हुनुहुन्छ (तल हेर्नुहोस्)।")
    rec = getattr(project, "ward_recommendation", None)
    rec_link = ""
    if rec is not None:
        rec_link = rec.document.url if rec.source == "upload" and rec.document else \
            reverse("print_ward_recommendation", args=[project.id])
    return {
        "project": project, "mode": mode, "mode_label": MODE_LABELS[mode], "committee": committee,
        "rows": rows, "missing_count": len(missing), "problems": problems, "gender": gender_summary(rows),
        "conflicts": conflicts, "conflict_block": conflict_block,
        "amount": estimate_summary(getattr(project, "cost_estimate", None)),
        "estimate": getattr(project, "cost_estimate", None),
        "approval": getattr(project, "uc_approval", None),
        "recommendation": rec, "rec_link": rec_link,
        "formation_bs": bs_date(committee.formation_date) if committee else "",
        "start_bs": bs_date(committee.start_date) if committee else "",
        "end_bs": bs_date(committee.deadline) if committee else "",
        "can_edit_committee": committee is not None and has_perm(request.user, "uc.committee"),
    }


def _can_see_docs(user, project, mode):
    return bool(user_perms(user) & {"uc.member_docs", "uc.committee", "uc.approve"}) or can_approve(user, project, mode)


@login_required
def approve(request, project_id):
    """GET: स्वीकृत modal (सबै कागजात सहित). POST: स्वीकृत अभिलेख."""
    qs, _ = _scoped(request)
    project = get_object_or_404(qs, id=project_id)
    mode = project_uc_mode(project)
    allowed = can_approve(request.user, project, mode)
    if not allowed and not (hasattr(project, "uc_approval") and _can_see_docs(request.user, project, mode)):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>तपाईंलाई यो योजना स्वीकृत गर्ने अधिकार छैन।</div>",
                            status=403)
    ctx = _review_ctx(request, project, mode)

    if request.method == "POST":
        if not allowed:
            return HttpResponse("<p class='text-sm text-rose-600'>स्वीकृत गर्ने अधिकार छैन।</p>", status=403)
        if ctx["problems"]:
            return HttpResponse("<p class='text-sm text-rose-600'>" + " ".join(ctx["problems"]) + "</p>", status=400)
        name, post = approver_identity(request.user, mode)
        UCApproval.objects.create(project=project, mode=mode, approved_by=request.user,
                                  approver_name=name, approver_post=post,
                                  remarks=request.POST.get("remarks", "").strip())
        messages.success(request, f"“{project.name}” रुजु / स्वीकृत भयो। अब सम्झौता र कार्यादेश तयार गर्न सकिन्छ।")
        return _back_to_page(request, project.id)

    name, post = approver_identity(request.user, mode)
    return render(request, "Admin/User/_wf_approve_modal.html",
                  ctx | {"purpose": "approve", "can_approve": allowed, "name": name, "post": post})


@login_required
def committee_review(request, project_id):
    """सदस्य र कागजात (हेर्ने मात्र) — उही modal."""
    qs, _ = _scoped(request)
    project = get_object_or_404(qs, id=project_id)
    mode = project_uc_mode(project)
    if not _can_see_docs(request.user, project, mode):
        return HttpResponse("<div class='p-6 text-sm text-rose-600'>कागजात हेर्ने अनुमति छैन।</div>", status=403)
    ctx = _review_ctx(request, project, mode)
    return render(request, "Admin/User/_wf_approve_modal.html", ctx | {"purpose": "review", "can_approve": False})


@login_required
def person_doc(request, person_id, kind):
    """सदस्यको कागजात — लगइन र अनुमति भएकाले मात्र (media URL सार्वजनिक नगरी)."""
    if kind not in dict(DOC_KINDS):
        raise Http404
    perms = user_perms(request.user)
    if not perms & {"uc.member_docs", "uc.committee", "uc.approve", "uc.approve_ward"}:
        return HttpResponse("अनुमति छैन।", status=403)
    person = get_object_or_404(Person, id=person_id)
    wards = _user_wards(request.user)
    if wards is not None and not person.memberships.filter(committee__project__ward_id__in=wards).exists() \
            and not has_perm(request.user, "uc.committee"):
        return HttpResponse("अनुमति छैन।", status=403)
    f = person.doc(kind)
    if not f:
        raise Http404
    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    resp = FileResponse(f.open("rb"), content_type=ctype)
    resp["Content-Disposition"] = "inline"
    resp["Cache-Control"] = "private, max-age=300"
    return resp


# ---------------------------------------------------------------- सिफारिस अपलोड
@login_required
def sifaris_upload(request, project_id, kind):
    """Upload a सिफारिस the ward sent on paper. kind: agreement | payment."""
    if not has_perm(request.user, "uc.sifaris_upload"):
        return HttpResponse("<p class='text-sm text-rose-600'>अपलोड गर्ने अधिकार छैन।</p>", status=403)
    qs, _ = _scoped(request)
    project = get_object_or_404(qs, id=project_id)
    model = WardRecommendation if kind == "agreement" else ProjectCompletionRecommendation
    related = "ward_recommendation" if kind == "agreement" else "completion_recommendation"
    title = "सम्झौताका लागि वडा सिफारिस" if kind == "agreement" else "काम सम्पन्न / भुक्तानीका लागि वडा सिफारिस"
    errors = []
    if hasattr(project, related):
        errors.append("यो सिफारिस पहिले नै राखिएको छ।")
    if kind == "payment" and not hasattr(project, "final_payment"):
        errors.append("पहिले अन्तिम मूल्याङ्कन गर्नुहोस्।")

    if request.method == "POST" and not errors:
        f = request.FILES.get("document")
        date_bs = (request.POST.get("recommendation_date") or "").strip()
        if not f:
            errors.append("सिफारिसको स्क्यान (PDF वा फोटो) छान्नुहोस्।")
        elif not f.name.lower().endswith(UPLOAD_TYPES):
            errors.append("PDF, JPG वा PNG मात्र।")
        elif f.size > UPLOAD_MAX_MB * 1024 * 1024:
            errors.append(f"फाइल {UPLOAD_MAX_MB} MB भन्दा सानो हुनुपर्छ।")
        date_ad = None
        if date_bs:
            from .views import convert_nepali_to_english

            date_ad = convert_nepali_to_english(date_bs.translate(str.maketrans("०१२३४५६७८९", "0123456789")))
            if not date_ad:
                errors.append("मिति मिलेन (YYYY-MM-DD)।")
        if not errors:
            from datetime import date

            model.objects.create(
                project=project, source="upload", document=f, uploaded_by=request.user,
                letter_number=request.POST.get("letter_number", "").strip() or None,
                chalani_number=request.POST.get("chalani_number", "").strip() or None,
                recommendation_date=date_ad or date.today(),
                remarks=request.POST.get("remarks", "").strip(),
            )
            messages.success(request, f"“{project.name}” को {title} अपलोड भयो।")
            return _back_to_page(request, project.id)

    return render(request, "Admin/User/_wf_sifaris_form.html", {
        "project": project, "kind": kind, "title": title, "errors": errors,
        "post": request.POST if request.method == "POST" else {},
    })


# ---------------------------------------------------------------- स्वीकृत गर्ने अधिकारी (delegation)
@login_required
def approvers(request):
    """"uc.delegate" अनुमति भएका (CAO, Admin) ले स्वीकृतको अधिकार (उपभोक्ता समिति, बोलपत्र, दरभाउपत्र,
    सोझै/अमानत, खरिद योजना) अरू अधिकृतलाई दिने/हटाउने — प्रकारअनुसार छुट्टाछुट्टै।"""
    from accounts.permissions import DELEGABLE, DELEGATE_TO, role_perms

    if not has_perm(request.user, "uc.delegate"):
        return redirect("unauthorized")
    codes = [c for c, *_ in DELEGABLE]
    from letters import signers as sg

    if request.method == "POST" and request.POST.get("form") == "signer":
        # पत्रमा हस्ताक्षर गर्ने अधिकारी (प्रकारअनुसार) — खाली = प्रमुख प्रशासकीय अधिकृत आफैँ
        from letters.models import LetterSigner

        kind = request.POST.get("kind", "")
        if kind in sg.KIND_LABEL:
            uid = request.POST.get("user_id", "")
            if uid.isdigit():
                u = get_object_or_404(CustomUser, id=uid, is_active=True)
                if u.user_type in sg.SIGN_TO:
                    LetterSigner.objects.update_or_create(kind=kind, defaults={
                        "user": u, "post": (request.POST.get("post") or "").strip()[:120], "granted_by": request.user})
                    messages.success(request, f"“{sg.KIND_LABEL[kind]}” मा अब {sg.person_name(u)} ले हस्ताक्षर गर्नुहुनेछ।")
            else:
                LetterSigner.objects.filter(kind=kind).delete()
                messages.success(request, f"“{sg.KIND_LABEL[kind]}” मा प्रमुख प्रशासकीय अधिकृत आफैँ (प्रत्यायोजन हटाइयो)।")
        return redirect(reverse("uc_approvers") + "#signers")

    if request.method == "POST":
        user = get_object_or_404(CustomUser, id=request.POST.get("user_id"))
        label = staff_names().get(user.id) or user.get_full_name() or user.mobile
        perm = request.POST.get("perm", "")
        chosen = codes if perm == "all" else [perm] if perm in codes else []
        action = request.POST.get("action")
        if action == "grant" and user.user_type in DELEGATE_TO and chosen:
            for c in chosen:
                UserPermission.objects.get_or_create(user=user, perm=c, defaults={"granted_by": request.user})
            messages.success(request, f"{label} लाई {'सबै' if perm == 'all' else dict((c, t) for c, t, _ in DELEGABLE)[perm]} स्वीकृत गर्ने अधिकार दिइयो।")
        elif action == "revoke" and chosen:
            UserPermission.objects.filter(user=user, perm__in=chosen).delete()
            messages.success(request, f"{label} को {'सबै प्रत्यायोजित' if perm == 'all' else dict((c, t) for c, t, _ in DELEGABLE)[perm]} अधिकार हटाइयो।")
        clear_cache(user)
        from accounts.mywork import bump

        bump()
        return redirect("uc_approvers")

    grants = {}
    for up in UserPermission.objects.filter(perm__in=codes).select_related("granted_by"):
        grants.setdefault(up.user_id, {})[up.perm] = up
    names = staff_names()
    role_cache = {}
    officers = []
    for u in CustomUser.objects.filter(user_type__in=sorted(DELEGATE_TO), is_active=True).order_by("user_type", "id"):
        rp = role_cache.setdefault(u.user_type, role_perms(u.user_type))
        g = grants.get(u.id, {})
        cells = [{"code": c, "title": t, "by_role": c in rp, "grant": g.get(c)} for c, t, _ in DELEGABLE]
        officers.append({"user": u, "name": names.get(u.id) or u.get_full_name() or u.mobile,
                         "role": ROLE_LABEL.get(u.user_type, ""), "cells": cells,
                         "n": sum(1 for x in cells if x["grant"]), "can_more": any(not x["grant"] and not x["by_role"] for x in cells)})
    caos = [{"user": u, "name": names.get(u.id) or u.mobile} for u in CustomUser.objects.filter(user_type="2", is_active=True)]
    chairs = WardChairperson.objects.select_related("ward", "admin").order_by("ward__id")
    cur = sg.assignments()
    sign_users = [{"id": u.id, "name": names.get(u.id) or u.get_full_name() or u.mobile, "role": ROLE_LABEL.get(u.user_type, "")}
                  for u in CustomUser.objects.filter(user_type__in=sorted(sg.SIGN_TO), is_active=True).order_by("user_type", "id")]
    signer_rows = [{"kind": k, "label": lbl, "help": h, "a": cur.get(k),
                    "now": sg.signer(k, cur)} for k, lbl, h in sg.KINDS]
    return render(request, "Admin/User/uc_approvers.html", {"officers": officers, "caos": caos, "chairs": chairs,
                                                             "kinds": DELEGABLE, "signer_rows": signer_rows,
                                                             "sign_users": sign_users})


def staff_names():
    """user id -> कर्मचारीको नाम (प्रोफाइलबाट)."""
    names = {}
    for attr in ("admin", "cao", "planningofficer", "engineer", "wadastaff", "wardsachib", "wardengineer",
                 "palikaengineer", "wardchairperson", "accountofficer"):
        rel = getattr(CustomUser, attr, None)
        if rel is None:
            continue
        for prof in rel.related.related_model.objects.all():
            if getattr(prof, "name", None):
                names[prof.admin_id] = prof.name
    return names
