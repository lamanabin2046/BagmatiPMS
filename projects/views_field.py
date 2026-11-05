"""साइट (मोबाइल) — योजनास्थलबाट GPS फोटो र प्रगति; नागरिक पेज — सार्वजनिक योजना विवरण (लगइन नचाहिने)."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Max, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Ward
from accounts.permissions import user_perms

from . import field as fd
from .models import FiscalYear, Project, ProjectTimeline


def _user_wards(user):
    from usercommittee.views_workflow import _user_wards as uw

    return uw(user)


def _limits():
    from .procurement import limits

    return limits()


def _open_fy():
    fys = list(FiscalYear.objects.order_by("-name"))
    open_ = [f for f in fys if not f.closed_at]
    return (open_[-1] if open_ else (fys[0] if fys else None)), fys


# ================================================================ साइट (मोबाइल)
@login_required
def field_home(request):
    P = user_perms(request.user)
    if not P & {"field.app", "field.view"}:
        return redirect("unauthorized")
    can_upload = "field.app" in P
    fy, fys = _open_fy()
    sel = request.GET.get("fiscalyear", "")
    fy = next((f for f in fys if str(f.id) == sel), fy)
    qs = Project.objects.filter(fiscalyear=fy).select_related("ward", "procurement_type")
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(address__icontains=q))
    show = request.GET.get("show", "")
    if show != "all":
        qs = qs.exclude(status=2)
    qs = qs.annotate(last_photo=Max("timelines__created_at"), n_photos=Count("timelines"))
    has = request.GET.get("has", "" if can_upload else "1")       # हेर्ने मात्र भए पूर्वनिर्धारित: फोटो भएका
    if has == "1":
        qs = qs.filter(n_photos__gt=0)
    qs = qs.order_by("-last_photo", "ward__name", "name") if has == "1" else qs.order_by("ward__name", "name")
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    rows = []
    for p in page.object_list:
        rows.append({"p": p, "progress": fd.latest_progress(p), "last": p.last_photo, "n": p.n_photos})
    return render(request, "projects/field_home.html", {"rows": rows, "page": page, "fy": fy, "fiscal_years": fys, "q": q,
                                                        "show": show, "has": has, "can_upload": can_upload})


@login_required
def field_project(request, pid):
    P = user_perms(request.user)
    if not P & {"field.app", "field.view"}:
        return redirect("unauthorized")
    can_upload = "field.app" in P
    if request.method == "POST" and not can_upload:     # हेर्ने मात्र — फोटो राख्न नमिल्ने
        messages.error(request, "तपाईंलाई साइट फोटो हेर्ने मात्र अनुमति छ — फोटो इन्जिनियरले राख्नुहुन्छ।")
        return redirect("field_project", pid)
    qs = Project.objects.select_related("ward", "fiscalyear", "procurement_type")
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    project = get_object_or_404(qs, id=pid)
    L = _limits()
    prev = fd.latest_progress(project)
    errors = []
    if request.method == "POST":
        img = request.FILES.get("image")
        note = (request.POST.get("description") or "").strip()
        try:
            stage = int(request.POST.get("stage") or 0)
        except ValueError:
            stage = 0
        prog_raw = (request.POST.get("progress_pct") or "").strip()
        progress = int(prog_raw) if prog_raw.isdigit() else None
        lat, lng, acc = fd.parse_coord(request.POST.get("lat"), request.POST.get("lng"), request.POST.get("acc"))
        no_gps = (request.POST.get("no_gps_reason") or "").strip()
        far_reason = (request.POST.get("far_reason") or "").strip()
        if img is None:
            errors.append("फोटो खिच्नुहोस् / छान्नुहोस्।")
        elif img.size > fd.MAX_UPLOAD:
            errors.append("फोटो १५ MB भन्दा ठूलो भयो।")
        if stage not in dict(ProjectTimeline.STAGE_CHOICES):
            errors.append("चरण छान्नुहोस् (काम सुरु अघि / भइरहेको / सम्पन्न)।")
        if not note:
            errors.append("के देखियो — छोटो विवरण लेख्नुहोस्।")
        if progress is not None and not (0 <= progress <= 100):
            errors.append("भौतिक प्रगति ० देखि १०० प्रतिशत।")
        if lat is None and not no_gps:
            errors.append("GPS स्थान आएन — मोबाइलको Location खोलेर फेरि प्रयास गर्नुहोस्, नभए कारण लेख्नुहोस्।")
        dist = None
        if lat is not None and project.latitude is not None:
            dist = fd.distance_m(project.latitude, project.longitude, lat, lng)
            if dist > L.field_max_distance and not far_reason:
                errors.append(f"फोटो योजना स्थलबाट {dist:,} मिटर टाढाबाट खिचिएको देखियो (सीमा {L.field_max_distance:,} मि.) — "
                              "साइटमै पुगेर खिच्नुहोस्, नभए कारण लेख्नुहोस्।")
        if progress is not None and prev is not None and progress < prev and "घट" not in note:
            errors.append(f"अघिल्लो प्रगति {prev}% थियो — कम देखाउँदा विवरणमा कारण (\"घटेको\" कारण) लेख्नुहोस्।")
        data = None
        if not errors:
            now = timezone.localtime()
            from biddings.views_workflow import to_bs
            lines = [f"{to_bs(now.date())} {now:%H:%M} NPT | Project #{project.id} {fd.ascii_name(project.name)}".strip(),
                     (f"GPS {lat}, {lng}" + (f" +/-{acc}m" if acc else "") if lat is not None else "GPS: not available")
                     + (f" | {dist:,} m from site" if dist is not None else "")
                     + (f" | Progress {progress}%" if progress is not None else "")]
            try:
                data = fd.stamp(img, lines)
            except ValueError as e:
                errors.append(str(e))
        if not errors:
            desc = note
            if lat is None:
                desc += f"\n(GPS नभएको कारण: {no_gps})"
            if far_reason:
                desc += f"\n(टाढाबाट खिचेको कारण: {far_reason})"
            t = ProjectTimeline(project=project, stage=stage, description=desc, uploaded_by=request.user, latitude=lat,
                                longitude=lng, accuracy=acc, distance_m=dist, progress_pct=progress, from_field=True,
                                is_public=not request.POST.get("private"))
            t.image.save(f"site-{project.id}-{timezone.now():%Y%m%d%H%M%S}.jpg", ContentFile(data), save=False)
            t.save()
            if lat is not None and project.latitude is None and request.POST.get("set_location"):
                project.latitude, project.longitude = lat, lng
                project.save(update_fields=["latitude", "longitude"])
                messages.info(request, "यो स्थान योजना स्थलका रूपमा तोकियो — अबका फोटो यसैसँग दाँजिन्छन्।")
            from usercommittee.models import ActivityLog
            ActivityLog.objects.create(user=request.user, action="create", model_name="साइट फोटो", object_id=t.id,
                                       object_repr=f"{t.get_stage_display()}"[:250], project_name=project.name[:250],
                                       note=(f"GPS {lat},{lng}" if lat is not None else "GPS छैन") + (f", प्रगति {progress}%" if progress is not None else ""))
            messages.success(request, "साइट फोटो सुरक्षित भयो ✅" + (f" — प्रगति {progress}%" if progress is not None else ""))
            return redirect("field_project", project.id)
    photos = list(project.timelines.select_related("uploaded_by").order_by("-created_at")[:20 if can_upload else 200])
    stage_filter = request.GET.get("stage", "")
    shown = [t for t in photos if not stage_filter or str(t.stage) == stage_filter]
    stage_default = ProjectTimeline.STAGE_BEFORE if not photos else (
        ProjectTimeline.STAGE_AFTER if project.status == 2 else ProjectTimeline.STAGE_DURING)
    return render(request, "projects/field_project.html", {
        "p": project, "photos": photos, "errors": errors, "prev": prev, "L": L, "d": request.POST if request.method == "POST" else {},
        "stages": ProjectTimeline.STAGE_CHOICES, "stage_default": stage_default, "P": P,
        "can_upload": can_upload, "shown": shown, "stage_filter": stage_filter,
        "stage_counts": {k: sum(1 for t in photos if t.stage == k) for k, _l in ProjectTimeline.STAGE_CHOICES},
    })


# ================================================================ नागरिक पेज (लगइन नचाहिने)
def _citizen_on():
    return _limits().citizen_portal


def _public_rows(fy):
    """प्रति योजना सार्वजनिक विवरण (१० मिनेट cache)."""
    key = f"citizen:{connection.schema_name}:{cache.get(f'mywork:ver:{connection.schema_name}', 0)}:{fy.id}"
    rows = cache.get(key)
    if rows is not None:
        return rows
    from usercommittee.reports import all_rows

    projects = list(Project.objects.filter(fiscalyear=fy).select_related("ward", "procurement_type"))
    agg = {}
    for r in all_rows([p.id for p in projects]):
        x = agg.setdefault(r["p"].id, {"kind": r["kind_label"], "party": r.get("party", ""), "contract": r.get("contract"),
                                       "paid": 0, "status": r["status_label"], "st": r["status"]})
        x["paid"] += float(r["gross"])
    progress = {}
    for t in ProjectTimeline.objects.filter(project__in=projects, progress_pct__isnull=False).order_by("created_at"):
        progress[t.project_id] = t.progress_pct
    photos = {}
    for t in ProjectTimeline.objects.filter(project__in=projects, is_public=True).values_list("project_id", flat=True):
        photos[t] = photos.get(t, 0) + 1
    rows = []
    for p in projects:
        x = agg.get(p.id, {"kind": "", "party": "", "contract": None, "paid": 0, "status": "प्रक्रिया सुरु नभएको", "st": "not_started"})
        prog = progress.get(p.id)
        if prog is None and x["st"] in ("completed", "paid"):
            prog = 100
        rows.append({"id": p.id, "name": p.name, "ward": p.ward.name if p.ward else "", "ward_id": p.ward_id, "budget": float(p.budget or 0),
                     "kind": x["kind"], "party": x["party"], "contract": float(x["contract"]) if x["contract"] else None,
                     "paid": x["paid"], "status": x["status"], "st": x["st"], "progress": prog, "photos": photos.get(p.id, 0),
                     "lat": float(p.latitude) if p.latitude is not None else None,
                     "lng": float(p.longitude) if p.longitude is not None else None, "address": p.address})
    cache.set(key, rows, 600)
    return rows


def citizen_list(request):
    if not _citizen_on():
        raise Http404
    fys = [f for f in FiscalYear.objects.order_by("-name") if Project.objects.filter(fiscalyear=f).exists()]
    sel = request.GET.get("fiscalyear", "")
    fy = next((f for f in fys if str(f.id) == sel), fys[0] if fys else None)
    rows = _public_rows(fy) if fy else []
    ward = request.GET.get("ward", "")
    q = (request.GET.get("q") or "").strip()
    st = request.GET.get("status", "")
    all_rows = rows
    if ward.isdigit():
        rows = [r for r in rows if str(r["ward_id"]) == ward]
    if q:
        rows = [r for r in rows if q in r["name"] or q in (r["party"] or "") or q in (r["address"] or "")]
    if st == "completed":
        rows = [r for r in rows if r["st"] in ("completed", "paid")]
    elif st == "running":
        rows = [r for r in rows if r["st"] == "running"]
    elif st == "not_started":
        rows = [r for r in rows if r["st"] == "not_started"]
    summary = {"n": len(all_rows), "budget": sum(r["budget"] for r in all_rows), "paid": sum(r["paid"] for r in all_rows),
               "done": sum(1 for r in all_rows if r["st"] in ("completed", "paid")),
               "running": sum(1 for r in all_rows if r["st"] == "running")}
    page = Paginator(rows, 30).get_page(request.GET.get("page"))
    keep = request.GET.copy()
    keep.pop("page", None)
    return render(request, "projects/citizen_list.html", {
        "fy": fy, "fiscal_years": fys, "page": page, "summary": summary, "f": {"ward": ward, "q": q, "status": st},
        "wards": Ward.objects.all(), "qs": keep.urlencode(), "count": len(rows),
    })


def citizen_project(request, pid):
    if not _citizen_on():
        raise Http404
    p = get_object_or_404(Project.objects.select_related("ward", "fiscalyear"), id=pid)
    row = next((r for r in _public_rows(p.fiscalyear) if r["id"] == p.id), None) if p.fiscalyear else None
    if row is None:
        raise Http404
    photos = list(p.timelines.filter(is_public=True).order_by("created_at"))
    groups = [(lbl, [x for x in photos if x.stage == k]) for k, lbl in ProjectTimeline.STAGE_CHOICES]
    groups = [(lbl, xs) for lbl, xs in groups if xs]
    other = [x for x in photos if x.stage is None]
    if other:
        groups.append(("अन्य", other))
    return render(request, "projects/citizen_project.html", {"p": p, "r": row, "groups": groups})


def citizen_photo(request, tid):
    """सार्वजनिक फोटो मात्र (media फोल्डर लगइनबिना खुल्दैन)."""
    if not _citizen_on():
        raise Http404
    t = get_object_or_404(ProjectTimeline, id=tid, is_public=True)
    try:
        return FileResponse(t.image.open("rb"), content_type="image/jpeg")
    except Exception:
        raise Http404
