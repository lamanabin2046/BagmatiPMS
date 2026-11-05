"""नापी किताब पेज: BOQ (हातैले वा Excel), नापी दर्ता, भौतिक प्रगति, छाप्ने (नापी किताब / बिल सार)."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import user_perms

from . import mb
from .models import BOQItem, Measurement, Project

VIEW = {"mb.view", "mb.boq", "mb.measure"}


def _project(request, project_id):
    from usercommittee.views_workflow import _user_wards

    p = get_object_or_404(Project.objects.select_related("ward", "fiscalyear", "procurement_type"), id=project_id)
    wards = _user_wards(request.user)
    if wards is not None and p.ward_id not in wards:
        return None
    return p


def _workflow_url(project):
    from django.urls import reverse

    code = getattr(project.procurement_type, "code", "")
    if code == "uc":
        return reverse("usercommittee_workflow") + f"?open={project.id}"
    if code == "bid":
        return reverse("bid_workflow") + f"?open={project.id}"
    if code == "quot":
        return reverse("quot_workflow") + f"?open={project.id}"
    if code == "sanstha":
        return reverse("sanstha_workflow") + f"?open={project.id}"
    if code in ("direct", "amanat"):
        return reverse("minor_detail", args=[project.id])
    return reverse("view_projects")


@login_required
def mb_page(request, project_id):
    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    project = _project(request, project_id)
    if project is None:
        return redirect("unauthorized")
    if request.method == "POST":
        _post(request, project, P)
        return redirect(request.path + (f"#item-{request.POST.get('item')}" if request.POST.get("item") else ""))
    rows = mb.item_rows(project)
    from biddings.views_workflow import to_bs

    return render(request, "projects/mb.html", {
        "project": project, "rows": rows, "s": mb.summary(project, rows), "today_bs": to_bs(date.today()),
        "can_boq": "mb.boq" in P, "can_measure": "mb.measure" in P,
        "photos": list(project.timelines.order_by("-created_at")[:6]), "workflow_url": _workflow_url(project),
        "bills": sorted({m.bill_no for r in rows for m in r["measurements"] if m.bill_no}),
    })


def _post(request, project, P):
    from biddings.views_workflow import to_ad

    a = request.POST.get("action", "")
    if a in ("item_add", "item_del", "import") and "mb.boq" not in P:
        messages.error(request, "BOQ बदल्ने अनुमति छैन।")
        return
    if a in ("measure_add", "measure_del") and "mb.measure" not in P:
        messages.error(request, "नापी दर्ता गर्ने अनुमति छैन।")
        return

    if a == "item_add":
        desc = (request.POST.get("description") or "").strip()
        unit = (request.POST.get("unit") or "").strip()
        q, rate = mb.num(request.POST.get("quantity")), mb.num(request.POST.get("rate"))
        errs = []
        if not desc or not unit:
            errs.append("विवरण र एकाइ भर्नुहोस्।")
        if q in (None, "bad") or q <= 0 or rate in (None, "bad") or rate < 0:
            errs.append("परिमाण (० भन्दा बढी) र दर अङ्कमा भर्नुहोस्।")
        if errs:
            for e in errs:
                messages.error(request, e)
            return
        n = (project.boq_items.aggregate(m=Max("sort"))["m"] or 0) + 1
        BOQItem.objects.create(project=project, sn=(request.POST.get("sn") or str(n)).strip()[:20], description=desc,
                               unit=unit, quantity=q, rate=rate, sort=n)
        messages.success(request, "BOQ मा काम थपियो।")

    elif a == "item_del":
        it = project.boq_items.filter(id=request.POST.get("item") or 0).first()
        if it is None:
            return
        if it.measurements.exists():
            messages.error(request, "नापी भइसकेको काम हटाउन मिल्दैन।")
            return
        it.delete()
        messages.success(request, "काम हटाइयो।")

    elif a == "import":
        f = request.FILES.get("file")
        if not f:
            messages.error(request, "Excel फाइल छान्नुहोस्।")
            return
        items, errs = mb.parse_boq(f)
        for e in errs[:10]:
            messages.error(request, e)
        if not items:
            return
        if project.boq_items.filter(measurements__isnull=False).exists() and request.POST.get("replace"):
            messages.error(request, "नापी भइसकेकाले BOQ बदल्न मिल्दैन — नयाँ काम मात्र थपिन्छ।")
            return
        with transaction.atomic():
            if request.POST.get("replace"):
                project.boq_items.all().delete()
            n = project.boq_items.aggregate(m=Max("sort"))["m"] or 0
            for i, it in enumerate(items, start=1):
                BOQItem.objects.create(project=project, sort=n + i, **it)
        messages.success(request, f"{len(items)} वटा काम Excel बाट थपियो।")

    elif a == "measure_add":
        it = project.boq_items.filter(id=request.POST.get("item") or 0).first()
        if it is None:
            messages.error(request, "काम भेटिएन।")
            return
        day = to_ad(request.POST.get("date"))
        vals = {k: mb.num(request.POST.get(k)) for k in ("nos", "length", "breadth", "height", "quantity")}
        errs = []
        if day is None:
            errs.append("नापी मिति भर्नुहोस् (वि.सं. YYYY-MM-DD)।")
        elif day > date.today():
            errs.append("भविष्यको मितिमा नापी दर्ता गर्न मिल्दैन।")
        if any(v == "bad" for v in vals.values()):
            errs.append("आयाम / परिमाण अङ्कमा मात्र।")
        qty = None if errs else mb.compute_qty(vals["nos"], vals["length"], vals["breadth"], vals["height"], vals["quantity"])
        if not errs and (qty is None or qty <= 0):
            errs.append("आयाम वा परिमाण भर्नुहोस् (० भन्दा बढी)।")
        deduction = bool(request.POST.get("deduction"))
        if not errs and deduction:
            have = sum((m.signed_quantity for m in it.measurements.all()), mb.ZERO)
            if qty > have:
                errs.append(f"घटाउ परिमाण अहिलेसम्मको नापी ({have}) भन्दा बढी भयो।")
        if errs:
            for e in errs:
                messages.error(request, e)
            return
        Measurement.objects.create(item=it, date=day, location=(request.POST.get("location") or "").strip()[:150],
                                   nos=vals["nos"], length=vals["length"], breadth=vals["breadth"], height=vals["height"],
                                   quantity=qty, deduction=deduction, remarks=(request.POST.get("remarks") or "").strip()[:250],
                                   measured_by=request.user)
        total = sum((m.signed_quantity for m in it.measurements.all()), mb.ZERO)
        messages.success(request, f"नापी दर्ता — {qty} {it.unit}{' (घटाउ)' if deduction else ''}।")
        if total > it.quantity:
            messages.warning(request, f"“{it.description[:40]}” को नापी BOQ परिमाण {it.quantity} भन्दा बढी ({total}) — "
                                      "बढी परिमाणको भुक्तानीका लागि भेरिएसन आदेश चाहिन्छ।")

    elif a == "measure_del":
        m = Measurement.objects.filter(item__project=project, id=request.POST.get("id") or 0).first()
        if m is None:
            return
        if m.bill_no:
            messages.error(request, "बिलमा परिसकेको नापी हटाउन मिल्दैन।")
            return
        m.delete()
        messages.success(request, "नापी हटाइयो।")


@login_required
def mb_print(request, project_id):
    if not user_perms(request.user) & VIEW:
        return redirect("unauthorized")
    project = _project(request, project_id)
    if project is None:
        return redirect("unauthorized")
    rows = mb.item_rows(project)
    bill = request.GET.get("bill", "")
    bill = int(bill) if bill.isdigit() else None
    abstract = []
    if bill:
        for r in rows:
            prev = sum((m.signed_quantity for m in r["measurements"] if m.bill_no and m.bill_no < bill), mb.ZERO)
            this = sum((m.signed_quantity for m in r["measurements"] if m.bill_no == bill), mb.ZERO)
            if prev or this:
                rate = r["item"].rate
                abstract.append({"item": r["item"], "prev": prev, "this": this, "cum": prev + this,
                                 "prev_amt": prev * rate, "this_amt": this * rate, "cum_amt": (prev + this) * rate})
    return render(request, "projects/mb_print.html", {
        "project": project, "rows": rows, "s": mb.summary(project, rows), "bill": bill, "abstract": abstract,
        "abs_total": {k: sum((x[k] for x in abstract), mb.ZERO) for k in ("prev_amt", "this_amt", "cum_amt")},
        "today": date.today(), "back": f"/Projects/{project.id}/MB/",
    })
