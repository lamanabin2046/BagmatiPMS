"""हेडरको खोज — योजना, फर्म र राजस्व ठेक्का एकै ठाउँमा (अनुमति र वडाअनुसार)."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from accounts.permissions import user_perms


def _project_url(p):
    """योजनाको खरिद विधिअनुसार कार्यप्रवाह पेज."""
    from django.urls import reverse

    from projects.procurement import WORKFLOW_URL

    code = p.procurement_type.code if p.procurement_type_id else ""
    if code in WORKFLOW_URL:
        return reverse(WORKFLOW_URL[code]) + f"?open={p.id}"
    if code in ("direct", "amanat"):
        return reverse("minor_list") + f"?open={p.id}"
    return reverse("field_project", args=[p.id])


@login_required
def global_search(request):
    q = (request.GET.get("q") or "").strip()
    P = user_perms(request.user)
    groups = []
    if len(q) >= 2:
        from usercommittee.views_workflow import _user_wards

        wards = _user_wards(request.user)
        from projects.models import Project, RevenueSource

        qs = Project.objects.filter(Q(name__icontains=q) | Q(address__icontains=q)).select_related("fiscalyear", "ward", "procurement_type")
        if wards is not None:
            qs = qs.filter(ward_id__in=wards)
        rows = [{"title": p.name, "sub": f"आ.व. {p.fiscalyear.name if p.fiscalyear else ''}"
                 + (f" · वडा {p.ward.name}" if p.ward else "") + (f" · {p.procurement_type.name}" if p.procurement_type else ""),
                 "url": _project_url(p)} for p in qs.order_by("-id")[:25]]
        if rows:
            groups.append({"label": "योजना", "icon": "clipboard-list", "rows": rows})
        if P & {"firm.view", "firm.manage", "firm.blacklist"}:
            from django.urls import reverse

            from quatation.models import Suchikrit

            fq = Suchikrit.objects.filter(Q(firm_name__icontains=q) | Q(firm_pan__icontains=q) | Q(firm_owner__icontains=q))
            rows = [{"title": f.firm_name, "sub": " · ".join(x for x in (f.firm_pan and f"PAN {f.firm_pan}", f.firm_address) if x),
                     "url": reverse("firm_detail", args=[f.id])} for f in fq[:25]]
            if rows:
                groups.append({"label": "फर्म / निर्माण व्यवसायी", "icon": "hard-hat", "rows": rows})
        if P & {"rev.view", "rev.manage", "rev.approve", "rev.survey", "rev.collect"}:
            from django.urls import reverse

            rq = RevenueSource.objects.filter(Q(name__icontains=q) | Q(location__icontains=q)).select_related("fiscalyear")
            if wards is not None:
                rq = rq.filter(ward_id__in=wards)
            rows = [{"title": s.name, "sub": f"आ.व. {s.fiscalyear.name}", "url": reverse("revenue_list") + f"?open={s.id}"} for s in rq[:25]]
            if rows:
                groups.append({"label": "राजस्व आम्दानी", "icon": "landmark", "rows": rows})
    return render(request, "accounts/search.html", {"q": q, "groups": groups, "total": sum(len(g["rows"]) for g in groups)})
