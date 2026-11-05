"""सेटिङ → वडाहरू: पालिकाका वडा थप्ने, वडा अध्यक्षको नाम राख्ने, प्रयोग नभएको वडा हटाउने."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Ward
from .permissions import has_perm
from .wards import MAX_WARDS, ensure_wards, np_num, sorted_wards, ward_int, ward_usage


@login_required
def manage_wards(request):
    if not has_perm(request.user, "settings.office"):
        return redirect("unauthorized")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "set_total":
            raw = (request.POST.get("total") or "").strip()
            n = ward_int(raw)
            if n is None or not 1 <= n <= MAX_WARDS:
                messages.error(request, f"वडा संख्या १ देखि {np_num(MAX_WARDS)} सम्म हुनुपर्छ।")
            else:
                created = ensure_wards(n)
                if created:
                    messages.success(request, f"{np_num(len(created))} वटा वडा थपियो: "
                                              + ", ".join(w.name for w in created))
                else:
                    messages.info(request, f"वडा १–{np_num(n)} पहिले नै छन्।")

        elif action == "add_one":
            n = ward_int(request.POST.get("number"))
            if n is None or not 1 <= n <= MAX_WARDS:
                messages.error(request, "वडा नम्बर मिलेन।")
            elif any(ward_int(w.name) == n for w in Ward.objects.all()):
                messages.error(request, f"वडा नं. {np_num(n)} पहिले नै छ।")
            else:
                Ward.objects.create(name=np_num(n),
                                    chairperson=(request.POST.get("chairperson") or "").strip() or None)
                messages.success(request, f"वडा नं. {np_num(n)} थपियो।")

        elif action == "save":
            changed = 0
            for w in Ward.objects.all():
                key = f"chair_{w.id}"
                if key in request.POST:
                    val = (request.POST.get(key) or "").strip()[:250] or None
                    if val != w.chairperson:
                        w.chairperson = val
                        w.save(update_fields=["chairperson"])
                        changed += 1
            messages.success(request, f"{np_num(changed)} वटा वडाको विवरण सुरक्षित भयो।" if changed
                             else "केही परिवर्तन भएन।")

        elif action == "delete":
            w = get_object_or_404(Ward, id=request.POST.get("id"))
            used = ward_usage(w)
            if used:
                messages.error(request, f"वडा नं. {w.name} हटाउन मिल्दैन — जोडिएका: "
                                        + ", ".join(f"{k} {np_num(v)}" for k, v in used.items()))
            else:
                w.delete()
                messages.success(request, f"वडा नं. {w.name} हटाइयो।")

        return redirect("manage_wards")

    rows = [{"w": w, "num": ward_int(w.name), "used": ward_usage(w)} for w in sorted_wards()]
    nums = [r["num"] for r in rows if r["num"]]
    missing = [np_num(i) for i in range(1, (max(nums) if nums else 0) + 1) if i not in nums]
    return render(request, "Admin/Accounts/wards.html", {
        "rows": rows, "total": len(rows), "missing": missing, "max_wards": MAX_WARDS,
        "next_number": np_num((max(nums) if nums else 0) + 1),
    })
