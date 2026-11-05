"""फर्म / निर्माण व्यवसायी दर्ता: सूची, थप/सम्पादन, कालोसूची, कामको इतिहास."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import user_perms

from . import firms as fm

VIEW = {"firm.view", "firm.manage", "firm.blacklist"}
FIELDS = ("firm_name", "firm_owner", "firm_address", "firm_pan", "firm_contact", "email", "reg_no", "notes")


def _form_values(post, firm=None):
    from quatation.models import Suchikrit

    v = {k: (post.get(k) or "").strip() for k in FIELDS}
    v["kind"] = post.get("kind") if post.get("kind") in dict(Suchikrit.KINDS) else "contractor"
    v["contractor_class"] = post.get("contractor_class") if post.get("contractor_class") in dict(Suchikrit.CLASSES) else ""
    v["vat_registered"] = bool(post.get("vat_registered"))
    v["enlisted"] = bool(post.get("enlisted"))
    errors = []
    if not v["firm_name"]:
        errors.append("फर्मको नाम लेख्नुहोस्।")
    pan = v["firm_pan"]
    if pan and not (pan.isdigit() and len(pan) == 9):
        errors.append("PAN / VAT नम्बर ९ अङ्कको हुनुपर्छ।")
    dup = Suchikrit.objects.exclude(id=getattr(firm, "id", None))
    if pan and dup.filter(firm_pan=pan).exists():
        errors.append(f"PAN {pan} भएको फर्म पहिले नै दर्ता छ।")
    if v["firm_name"] and dup.filter(firm_name=v["firm_name"]).exists():
        errors.append(f"“{v['firm_name']}” नामको फर्म पहिले नै दर्ता छ।")
    return v, errors


@login_required
def firm_list(request):
    from quatation.models import Suchikrit

    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    if request.method == "POST":
        if "firm.manage" not in P:
            return redirect("unauthorized")
        v, errors = _form_values(request.POST)
        for e in errors:
            messages.error(request, e)
        if not errors:
            f = Suchikrit.objects.create(**v)
            messages.success(request, f"“{f.firm_name}” दर्ता भयो।")
            if (e := fm.blocked(f)):
                messages.warning(request, e)
            return redirect("firm_detail", f.id)
        return redirect("firm_list")
    f = {k: (request.GET.get(k) or "").strip() for k in ("q", "kind", "status")}
    qs = Suchikrit.objects.all().order_by("firm_name")
    if f["q"]:
        qs = qs.filter(Q(firm_name__icontains=f["q"]) | Q(firm_pan__icontains=f["q"]) | Q(firm_owner__icontains=f["q"]))
    if f["kind"] in dict(Suchikrit.KINDS):
        qs = qs.filter(kind=f["kind"])
    from .registry import norm
    ppmo_pans, ppmo_names = _ppmo_sets()
    rows = []
    for firm in qs.prefetch_related("bids__contract__final_payment"):
        bids = list(firm.bids.all())
        running = sum(1 for b in bids if getattr(b, "contract", None) and not getattr(b.contract, "final_payment", None))
        ppmo = bool((firm.firm_pan and firm.firm_pan in ppmo_pans) or norm(firm.firm_name) in ppmo_names)
        rows.append({"f": firm, "bids": len(bids), "running": running, "ppmo": ppmo})
    if f["status"] == "blacklisted":
        rows = [r for r in rows if r["f"].is_blacklisted or r["ppmo"]]
    elif f["status"] == "enlisted":
        rows = [r for r in rows if r["f"].enlisted and not r["f"].is_blacklisted]
    elif f["status"] == "inactive":
        rows = [r for r in rows if not r["f"].is_active]
    if request.GET.get("export") == "xlsx":
        return _xlsx(rows)
    keep = request.GET.copy()
    keep.pop("export", None)
    from .procurement import limits
    L = limits()
    return render(request, "projects/firm_list.html", {
        "ird_enabled": L.ird_lookup_enabled, "ppmo_count": _ppmo_count(), "ppmo_at": L.ppmo_imported_at,
        "rows": rows, "f": f, "kinds": Suchikrit.KINDS, "classes": Suchikrit.CLASSES, "qs": keep.urlencode(),
        "can_manage": "firm.manage" in P,
        "counts": {"all": Suchikrit.objects.count(), "blacklisted": sum(1 for r in rows if r["f"].is_blacklisted or r["ppmo"]) if f["status"] == "blacklisted" else
                   sum(1 for x in Suchikrit.objects.all() if x.is_blacklisted or ((x.firm_pan and x.firm_pan in ppmo_pans) or norm(x.firm_name) in ppmo_names)),
                   "enlisted": Suchikrit.objects.filter(enlisted=True, is_active=True).count()},
    })


@login_required
def firm_detail(request, firm_id):
    from quatation.models import Suchikrit

    from biddings.views_workflow import to_ad, to_bs

    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    firm = get_object_or_404(Suchikrit, id=firm_id)
    if request.method == "POST":
        a = request.POST.get("action")
        if a == "edit" and "firm.manage" in P:
            v, errors = _form_values(request.POST, firm)
            for e in errors:
                messages.error(request, e)
            if not errors:
                for k, val in v.items():
                    setattr(firm, k, val)
                firm.is_active = bool(request.POST.get("is_active"))
                firm.save()
                messages.success(request, "विवरण सुरक्षित भयो।")
        elif a == "ird" and "firm.manage" in P:
            _ird_refresh(request, firm)
        elif a == "blacklist" and "firm.blacklist" in P:
            ref = (request.POST.get("blacklist_ref") or "").strip()
            reason = (request.POST.get("blacklist_reason") or "").strip()
            raw = request.POST.get("blacklist_until") or ""
            until = to_ad(raw) if raw else None
            if not ref or not reason:
                messages.error(request, "कालोसूचीको निर्णय / सूचना र कारण लेख्नुहोस्।")
            elif raw and until is None:
                messages.error(request, "म्याद मिति मिलेन (वि.सं. YYYY-MM-DD)।")
            else:
                firm.blacklisted, firm.blacklist_ref, firm.blacklist_reason, firm.blacklist_until = True, ref, reason, until
                firm.save(update_fields=["blacklisted", "blacklist_ref", "blacklist_reason", "blacklist_until"])
                messages.success(request, f"“{firm.firm_name}” कालोसूचीमा राखियो।")
        elif a == "unblacklist" and "firm.blacklist" in P:
            firm.blacklisted = False
            firm.notes = (firm.notes + "\n" if firm.notes else "") + \
                f"कालोसूचीबाट हटाइयो ({(request.POST.get('lift_ref') or '').strip()}) — पहिलेको: {firm.blacklist_ref}"
            firm.save(update_fields=["blacklisted", "notes"])
            messages.success(request, f"“{firm.firm_name}” कालोसूचीबाट हटाइयो।")
        else:
            messages.error(request, "यो काम गर्ने अनुमति छैन।")
        return redirect("firm_detail", firm.id)
    rows, s = fm.history(firm)
    from .procurement import limits
    from .registry import ppmo_match
    return render(request, "projects/firm_detail.html", {
        "ppmo": ppmo_match(firm), "ird_enabled": limits().ird_lookup_enabled,
        "firm": firm, "rows": rows, "s": s, "kinds": Suchikrit.KINDS, "classes": Suchikrit.CLASSES,
        "can_manage": "firm.manage" in P, "can_blacklist": "firm.blacklist" in P,
        "until_bs": to_bs(firm.blacklist_until) if firm.blacklist_until else "",
    })


def _xlsx(rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "फर्म दर्ता"
    ws.append(["क्र.सं.", "फर्मको नाम", "प्रकार", "वर्ग", "PAN / VAT", "भ्याट दर्ता", "प्रोपाइटर", "ठेगाना", "सम्पर्क", "इमेल",
               "सूचीकृत", "बोलपत्र", "चालु ठेक्का", "स्थिति"])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True), PatternFill("solid", fgColor="E8EEFB")
    for i, r in enumerate(rows, start=1):
        f = r["f"]
        ws.append([i, f.firm_name, f.get_kind_display(), f.get_contractor_class_display() if f.contractor_class else "",
                   f.firm_pan, "हो" if f.vat_registered else "", f.firm_owner, f.firm_address, f.firm_contact, f.email,
                   "हो" if f.enlisted else "", r["bids"], r["running"],
                   "कालोसूची" if f.is_blacklisted else ("निष्क्रिय" if not f.is_active else "सक्रिय")])
    for n, w in enumerate([6, 32, 14, 8, 12, 9, 20, 24, 14, 22, 8, 8, 10, 10], start=1):
        ws.column_dimensions[ws.cell(row=1, column=n).column_letter].width = w
    ws.freeze_panes = "A2"
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="firms.xlsx"'
    wb.save(resp)
    return resp



def _ppmo_sets():
    from datetime import date

    from django.db.models import Q

    from .models import PPMOBlacklist

    active = PPMOBlacklist.objects.filter(Q(to_date__isnull=True) | Q(to_date__gte=date.today()))
    return set(active.exclude(pan="").values_list("pan", flat=True)), set(active.values_list("name_key", flat=True))


def _ppmo_count():
    from .models import PPMOBlacklist

    return PPMOBlacklist.objects.count()


def _ird_refresh(request, firm):
    from django.utils import timezone

    from .procurement import limits
    from .registry import LookupError_, lookup_pan

    try:
        d = lookup_pan(firm.firm_pan, limits())
    except LookupError_ as e:
        messages.error(request, str(e))
        return
    firm.ird_name = (d.get("name_np") or d.get("name_en") or "")[:250]
    firm.ird_status = (d.get("status") or "")[:100]
    firm.ird_data, firm.ird_checked_at = d, timezone.now()
    if not firm.firm_address and d.get("address"):
        firm.firm_address = d["address"][:250]
    firm.save()
    msg = f"IRD विवरण अद्यावधिक: {firm.ird_name} ({firm.ird_status or 'स्थिति खुलेन'})"
    messages.success(request, msg)
    if firm.ird_name and firm.ird_name.strip() not in (firm.firm_name.strip(), d.get("name_en", "").strip()):
        messages.warning(request, f"IRD मा दर्ता नाम “{firm.ird_name}” — यहाँको नाम “{firm.firm_name}” सँग फरक छ, जाँच्नुहोस्।")


@login_required
def pan_lookup(request):
    """फारमबाट (JS) — ?pan= → IRD विवरण JSON."""
    if not user_perms(request.user) & {"firm.manage", "bid.manage", "minor.manage", "quot.manage"}:
        return JsonResponse({"ok": False, "error": "अनुमति छैन।"}, status=403)
    from .procurement import limits
    from .registry import LookupError_, lookup_pan, ppmo_match

    pan = (request.GET.get("pan") or "").strip()
    try:
        d = lookup_pan(pan, limits())
    except LookupError_ as e:
        return JsonResponse({"ok": False, "error": str(e)})
    hit = ppmo_match(None, d.get("name_np") or d.get("name_en") or "", pan)
    existing = fm.find("", pan)
    return JsonResponse({"ok": True, "data": d, "ppmo": f"PPMO कालोसूचीमा छ — {hit.decision}" if hit else "",
                         "existing": {"id": existing.id, "name": existing.firm_name} if existing else None})


@login_required
def ppmo_list(request):
    """PPMO कालोसूची: आयात (Excel / CSV), खोज, दर्ताका फर्मसँग मिलेका."""
    from django.utils import timezone

    from .models import PPMOBlacklist
    from .procurement import forget_limits, limits
    from .registry import norm, parse_blacklist

    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    if request.method == "POST":
        if "firm.blacklist" not in P:
            return redirect("unauthorized")
        f = request.FILES.get("file")
        if not f:
            messages.error(request, "फाइल छान्नुहोस्।")
            return redirect("ppmo_list")
        items, errors = parse_blacklist(f, f.name)
        for e in errors[:5]:
            messages.error(request, e)
        if items:
            from django.db import transaction
            with transaction.atomic():
                if request.POST.get("replace"):
                    PPMOBlacklist.objects.all().delete()
                for it in items:
                    PPMOBlacklist.objects.create(name_key=norm(it["name"]), **it)
            L = limits()
            from .models import ProcurementLimits
            ProcurementLimits.objects.filter(id=L.id).update(ppmo_imported_at=timezone.now())
            forget_limits()
            messages.success(request, f"PPMO कालोसूचीका {len(items)} वटा फर्म आयात भयो।")
        return redirect("ppmo_list")
    q = (request.GET.get("q") or "").strip()
    qs = PPMOBlacklist.objects.all()
    if q:
        qs = qs.filter(name__icontains=q) | PPMOBlacklist.objects.filter(pan__icontains=q)
    from quatation.models import Suchikrit
    pans, names = _ppmo_sets()
    matched = [x for x in Suchikrit.objects.all() if (x.firm_pan and x.firm_pan in pans) or norm(x.firm_name) in names]
    return render(request, "projects/ppmo_list.html", {
        "rows": qs[:500], "total": PPMOBlacklist.objects.count(), "q": q, "matched": matched,
        "imported_at": limits().ppmo_imported_at, "can_import": "firm.blacklist" in P,
    })
