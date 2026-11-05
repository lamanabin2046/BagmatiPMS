"""आर्थिक वर्ष बन्द — स्न्यापसट, क्रमागत योजना अर्को आ.व. मा सार्ने, र आ.व. लक.

हरेक योजनाको निर्णय:
  completed  सम्पन्न / अन्तिम बिल भएको — त्यही आ.व. मा रहन्छ
  carried    क्रमागत — बहुवर्षीय (खरिद योजनामा "बहुवर्षीय" तोकिएको) योजना मात्र; कार्यप्रवाह, सम्झौता, धरौटी,
             जमानत सहित नयाँ आ.व. मा सर्छ;
             बजेट = अहिलेसम्मको खर्च + नयाँ आ.व. को आवंटन; अघिल्लो खर्च spent_before मा राखिन्छ
  frozen     रोक्का — त्यही आ.व. मा रहन्छ, आ.व. लक भएपछि भुक्तानी हुँदैन (बजेट फ्रिज) — एक वर्षे अधुरा योजना पनि
बन्दपछि नयाँ आ.व. चालु आ.व. हुन्छ (projects/fiscal.py)।
लक: बन्द आ.व. का योजनामा भुक्तानी र बजेट परिवर्तन रोकिन्छ (projects.budget.closed_fy_error)।
धरौटी फिर्ता र राजस्व असुली रोकिँदैन — ती अघिल्ला वर्षका दायित्व हुन्।
"""
from decimal import Decimal

ZERO = Decimal("0")


def D(v):
    return Decimal(str(v or 0))


def is_multi_year(p):
    """खरिद योजनामा बहुवर्षीय तोकिएको (उपभोक्ता समिति कहिल्यै होइन)।"""
    plan = getattr(p, "procurement_plan", None)
    return bool(plan and plan.multi_year and plan.method != "uc")


def preview(fy, wards=None):
    """[{p, kind_label, status, status_label, allocated, spent, committed, remaining, default, retention}]"""
    from usercommittee.reports import STATUS, all_rows

    from .deductions import retention_items
    from .models import Project

    qs = Project.objects.filter(fiscalyear=fy).select_related("ward", "procurement_type", "budget_head", "procurement_plan")
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    projects = list(qs)
    rows = all_rows([p.id for p in projects])
    agg = {}
    for r in rows:
        x = agg.setdefault(r["p"].id, {"kind_label": r["kind_label"], "status": r["status"], "spent": ZERO, "committed": ZERO})
        x["spent"] += D(r["gross"])
        x["committed"] = max(x["committed"], D(r.get("contract")))
    held = {}
    for it in retention_items([p.id for p in projects]):
        if it["status"] != "released":
            held[it["p"].id] = held.get(it["p"].id, ZERO) + it["held"]
    out = []
    for p in projects:
        x = agg.get(p.id, {"kind_label": "विधि नतोकिएको", "status": "not_started", "spent": ZERO, "committed": ZERO})
        allocated = D(p.budget)
        remaining = max(allocated - x["spent"], ZERO)
        st = x["status"]
        multi = is_multi_year(p)
        # बहुवर्षीय मात्र क्रमागत; एक वर्षे अधुरा योजना रोक्का (बजेट फ्रिज)
        default = "completed" if st in ("completed", "paid") else ("carried" if multi else "frozen")
        out.append({"p": p, "kind_label": x["kind_label"], "status": st, "status_label": STATUS.get(st, st), "multi_year": multi,
                    "allocated": allocated, "spent": x["spent"], "committed": x["committed"], "remaining": remaining,
                    "default": default, "retention": held.get(p.id, ZERO)})
    out.sort(key=lambda r: (["carried", "frozen", "completed"].index(r["default"]), str(r["p"].ward.name if r["p"].ward else ""),
                            r["p"].name))
    return out


def close(fy, to_fy, decisions, user, ref, wards=None):
    """decisions: {project_id: (action, new_allocation Decimal)}. स्न्यापसट + सार्ने + लक। (n_carried, n_frozen, n_completed)"""
    from django.db import transaction
    from django.utils import timezone

    from .models import YearEndLine

    rows = preview(fy, wards)
    counts = {"carried": 0, "frozen": 0, "completed": 0}
    with transaction.atomic():
        # लक खोली फेरि बन्द गर्दा: पहिले सारिएका क्रमागतका रेकर्ड राख्ने (ती योजना अब यस आ.व. मा छैनन्)
        YearEndLine.objects.filter(fiscalyear=fy).exclude(action="carried").delete()
        for r in rows:
            p = r["p"]
            action, new_alloc = decisions.get(p.id, (r["default"], r["remaining"]))
            if r["status"] in ("completed", "paid") and action == "carried":
                action = "completed"
            if action == "carried" and not r["multi_year"]:     # एक वर्षे योजना सार्न मिल्दैन
                action = "frozen"
            new_alloc = D(new_alloc) if action == "carried" else ZERO
            YearEndLine.objects.create(
                fiscalyear=fy, project=p, project_name=p.name[:250], ward_name=str(p.ward.name) if p.ward else "",
                kind_label=r["kind_label"], allocated=r["allocated"], spent=r["spent"], committed=r["committed"],
                status_label=r["status_label"], action=action, to_fiscalyear=to_fy if action == "carried" else None,
                new_allocation=new_alloc, retention_held=r["retention"])
            if action == "carried":
                p.carried_from = fy
                p.spent_before = r["spent"]
                p.fiscalyear = to_fy
                p.budget = float(r["spent"] + new_alloc)
                if p.budget_head_id and p.budget_head.fiscalyear_id != to_fy.id:
                    p.budget_head = None          # नयाँ आ.व. को शीर्षक फेरि तोक्नुपर्छ
                p.save(update_fields=["carried_from", "spent_before", "fiscalyear", "budget", "budget_head"])
            counts[action] += 1
        fy.closed_at, fy.closed_by, fy.close_ref = timezone.now(), user, ref
        fy.save(update_fields=["closed_at", "closed_by", "close_ref"])
        if to_fy is not None:                                   # नयाँ आ.व. चालु हुने
            from .fiscal import set_current

            set_current(to_fy)
    return counts
