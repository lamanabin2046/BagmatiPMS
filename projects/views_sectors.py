"""सेटिङ: क्षेत्र / उपक्षेत्र — थप्ने, नाम बदल्ने, सक्रिय/निष्क्रिय, (प्रयोग नभएका) हटाउने."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import has_perm

from .models import Sector, SubSector


@login_required
def sector_settings(request):
    if not has_perm(request.user, "settings.sectors"):
        return redirect("unauthorized")
    if request.method == "POST":
        action = request.POST.get("action", "")
        name = (request.POST.get("name") or "").strip()
        if action == "add_sector":
            if not name:
                messages.error(request, "क्षेत्रको नाम लेख्नुहोस्।")
            elif Sector.objects.filter(name=name).exists():
                messages.error(request, f"“{name}” क्षेत्र पहिले नै छ।")
            else:
                Sector.objects.create(name=name, sort=(Sector.objects.aggregate(m=Max("sort"))["m"] or 0) + 1)
                messages.success(request, f"क्षेत्र “{name}” थपियो।")
        elif action == "add_sub":
            sector = get_object_or_404(Sector, id=request.POST.get("sector_id"))
            if not name:
                messages.error(request, "उपक्षेत्रको नाम लेख्नुहोस्।")
            elif sector.subsectors.filter(name=name).exists():
                messages.error(request, f"“{name}” उपक्षेत्र “{sector.name}” मा पहिले नै छ।")
            else:
                SubSector.objects.create(sector=sector, name=name,
                                         sort=(sector.subsectors.aggregate(m=Max("sort"))["m"] or 0) + 1)
                messages.success(request, f"“{sector.name}” मा उपक्षेत्र “{name}” थपियो।")
        elif action in ("rename_sector", "toggle_sector", "delete_sector"):
            obj = get_object_or_404(Sector, id=request.POST.get("id"))
            _change(request, obj, action.split("_")[0], name, "क्षेत्र")
        elif action in ("rename_sub", "toggle_sub", "delete_sub"):
            obj = get_object_or_404(SubSector, id=request.POST.get("id"))
            _change(request, obj, action.split("_")[0], name, "उपक्षेत्र")
        return redirect("sector_settings")

    sectors = (Sector.objects.annotate(n_projects=Count("projects", distinct=True))
               .prefetch_related("subsectors"))
    sub_counts = dict(SubSector.objects.annotate(n=Count("projects")).values_list("id", "n"))
    rows = []
    for s in sectors:
        subs = list(s.subsectors.all())
        for x in subs:
            x.n_projects = sub_counts.get(x.id, 0)
        rows.append({"s": s, "subs": subs})
    return render(request, "projects/sector_settings.html", {"rows": rows})


def _change(request, obj, op, name, label):
    if op == "rename":
        if not name:
            messages.error(request, "नाम खाली राख्न मिल्दैन।")
            return
        obj.name = name
        obj.save(update_fields=["name"])
        messages.success(request, f"{label}को नाम “{name}” राखियो।")
    elif op == "toggle":
        obj.is_active = not obj.is_active
        obj.save(update_fields=["is_active"])
        messages.success(request, f"“{obj.name}” {'सक्रिय' if obj.is_active else 'निष्क्रिय'} गरियो।")
    elif op == "delete":
        used = obj.projects.exists() or (isinstance(obj, Sector) and SubSector.objects.filter(sector=obj, projects__isnull=False).exists())
        if used:
            messages.error(request, f"“{obj.name}” योजनामा प्रयोग भइसकेकाले हटाउन मिल्दैन — निष्क्रिय गर्नुहोस्।")
            return
        obj.delete()
        messages.success(request, f"“{obj.name}” हटाइयो।")
