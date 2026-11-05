"""भूमिकाअनुसार ड्यासबोर्ड (CAO, योजना अधिकृत …) — चालु आ.व. का कार्यप्रवाहबाट।

scan(): उपभोक्ता समिति / बोलपत्र / दरभाउपत्रका हरेक योजनाको हालको चरण, स्वीकृति पर्खाइ, म्याद (मेरो कामकै हिसाब)।
५ मिनेट cache — कुनै फारम सुरक्षित हुँदा (मेरो कामको version) आफैँ ताजा।
"""
from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.urls import reverse

ZERO = Decimal("0")
KIND = {"uc": "उपभोक्ता समिति", "bid": "बोलपत्र ठेक्का", "quot": "दरभाउपत्र खरिद"}
DETAIL = {"uc": "usercommittee_workflow", "bid": "bid_workflow", "quot": "quot_workflow"}


def _last_date(steps):
    ds = [s.get("date") for s in steps if s.get("state") == "done" and s.get("date")]
    ds = [d for d in ds if isinstance(d, date)]
    return max(ds) if ds else None


def _scan(user, wards):
    from biddings import workflow as bw
    from quatation import workflow as qw
    from usercommittee import workflow as uc

    from .fiscal import current_fy_id

    cid = current_fy_id()
    mods = [
        ("uc", uc.workflow_queryset(), lambda p: uc.project_workflow(p, user.user_type, user),
         lambda p, s: s["current_key"] == "approval" and uc.can_approve(user, p, s["mode"]), uc.STEP_INFO),
        ("bid", bw.workflow_queryset(), lambda p: bw.bid_workflow(p, user),
         lambda p, s, ok=bw.can_approve(user): ok and s["current_key"] == "approval", bw.STEP_INFO),
        ("quot", qw.workflow_queryset(), lambda p: qw.quot_workflow(p, user),
         lambda p, s, ok=qw.can_approve(user): ok and s["current_key"] == "approval", qw.STEP_INFO),
    ]
    rows = []
    today = date.today()
    for kind, qs, wf, waiting, info in mods:
        if cid:
            qs = qs.filter(fiscalyear_id=cid)
        if wards is not None:
            qs = qs.filter(ward_id__in=wards)
        for p in qs:
            steps, s = wf(p)
            keys = [x["key"] for x in steps]
            last = _last_date(steps)
            agreed = "agreement" in keys and any(x["key"] == "agreement" and x["state"] == "done" for x in steps)
            rows.append({
                "id": p.id, "name": p.name, "ward": getattr(p.ward, "name", "") if p.ward_id else "",
                "ward_id": p.ward_id, "kind": kind, "kind_label": KIND[kind], "budget": Decimal(str(p.budget or 0)),
                "key": s["current_key"], "label": (info.get(s["current_key"]) or ("", s.get("current_label", "")))[1]
                if s["current_key"] in info else s.get("current_label", ""),
                "completed": bool(s["completed"]), "approve": bool(not s["completed"] and waiting(p, s)),
                "overdue": bool(s.get("overdue")), "days_late": s.get("days_late") or 0,
                "days_left": s.get("days_left"), "deadline_bs": s.get("deadline_bs") or "",
                "waiting": (today - last).days if last else None, "agreed": agreed,
                "audit": {x["key"]: x["state"] for x in steps}.get("public_audit"),
                # लागत अनुमान बाँकी (समिति गठनअघि पनि भर्न मिल्ने)
                "est_open": kind == "uc" and any(x["key"] == "estimate" and x["state"] != "done" for x in steps),
                "url": reverse(DETAIL[kind]) + f"?open={p.id}",
            })
    return rows


def scan(user, wards):
    ver = cache.get(f"mywork:ver:{connection.schema_name}", 0)
    w = "all" if wards is None else "-".join(map(str, sorted(wards)))
    key = f"roledash:{connection.schema_name}:{ver}:{user.pk}:{w}"
    rows = cache.get(key)
    if rows is None:
        rows = _scan(user, wards)
        cache.set(key, rows, 300)
    return rows


def ward_status(pct):
    if pct >= 50:
        return "उत्कृष्ट", "bg-emerald-50 text-emerald-700"
    if pct >= 40:
        return "सन्तोषजनक", "bg-teal-50 text-teal-700"
    if pct >= 30:
        return "सामान्य", "bg-slate-100 text-slate-600"
    return "अनुगमन आवश्यक", "bg-amber-50 text-amber-800"


def approvals_for(user, fy, wards, rows=None):
    """यो प्रयोगकर्ताले (भूमिका वा CAO को प्रत्यायोजनबाट) स्वीकृत गर्न मिल्ने, पर्खिरहेका फाइल:
    उपभोक्ता समिति / बोलपत्र / दरभाउपत्र (कार्यप्रवाह), सोझै / अमानत / संस्था, खरिद योजना (मस्यौदा)."""
    from accounts.permissions import user_perms

    from . import minor as mn
    from .models import ProcurementPlan

    P = user_perms(user)
    rows = scan(user, wards) if rows is None else rows
    approvals = [r for r in rows if r["approve"]]
    today = date.today()
    if "minor.approve" in P and fy:
        qs = mn.workflow_queryset().filter(fiscalyear=fy)
        if wards is not None:
            qs = qs.filter(ward_id__in=wards)
        for p in qs:
            _steps, sm = mn.workflow(p)
            if not sm["completed"] and sm["current_key"] == "approval":
                approvals.append({"id": p.id, "name": p.name, "ward": getattr(p.ward, "name", "") if p.ward_id else "",
                                  "kind": "minor", "kind_label": mn.METHOD_LABEL.get(sm["method"], "सोझै / अमानत"),
                                  "budget": Decimal(str(p.budget or 0)), "label": "छनौट / अमानत स्वीकृत",
                                  "waiting": None, "url": (reverse("sanstha_workflow") + "?stage=to_approve" if sm["method"] == "sanstha"
                                          else reverse("minor_detail", args=[p.id]))})
    plans = []
    if "app.approve" in P and fy:
        plans = ProcurementPlan.objects.filter(project__fiscalyear=fy, status="draft").select_related("project__ward")
        if wards is not None:
            plans = plans.filter(project__ward_id__in=wards)
    for pl in plans:
        p = pl.project
        approvals.append({"id": p.id, "name": p.name, "ward": getattr(p.ward, "name", "") if p.ward_id else "",
                          "kind": "app", "kind_label": "खरिद योजना", "budget": Decimal(str(pl.estimated_cost or 0)),
                          "label": "खरिद योजना स्वीकृति",
                          "waiting": (today - pl.created_at.date()).days if getattr(pl, "created_at", None) else None,
                          "url": reverse("app_plan", args=[p.id])})
    approvals.sort(key=lambda r: -(r["waiting"] or 0))
    return approvals


def cao(user, fy, wards, d):
    """CAO: स्वीकृति पर्खाइ (कार्यप्रवाह + खरिद योजना), म्याद नाघेका, वडागत स्थिति।"""
    rows = scan(user, wards)
    approvals = approvals_for(user, fy, wards, rows)
    overdue = sorted([r for r in rows if r["overdue"] and not r["completed"]], key=lambda r: -r["days_late"])
    wards_out = []
    for w in d["wards"]:
        label, tone = ward_status(w["pct"])
        wards_out.append(dict(w, status=label, tone=tone))
    total_alloc = sum((m["allocated"] for m in d["methods"]), ZERO) or Decimal(1)
    methods = [dict(m, share=float(m["allocated"] * 100 / total_alloc)) for m in d["methods"]]
    return {"approvals": approvals, "approval_count": len(approvals), "overdue": overdue, "overdue_count": len(overdue),
            "wards": wards_out, "methods": methods}


def planning(user, fy, wards, d):
    """योजना अधिकृत: दर्ता, विधि, खरिद योजना, उपभोक्ता समिति कार्यप्रवाहका चरण, वडागत सम्झौता।"""
    from usercommittee import workflow as uc

    from .models import ProcurementPlan, Project

    rows = scan(user, wards)
    projects = Project.objects.filter(fiscalyear=fy) if fy else Project.objects.none()
    if wards is not None:
        projects = projects.filter(ward_id__in=wards)
    plans = ProcurementPlan.objects.filter(project__in=projects)
    ucr = [r for r in rows if r["kind"] == "uc"]
    stages = []
    for key in uc.STEP_INFO:
        if key == "project":
            continue
        short, label = uc.STEP_INFO[key]
        stages.append({"key": key, "short": short, "label": label,
                       "n": sum(1 for r in ucr if not r["completed"] and (r["key"] == key or (key == "estimate" and r.get("est_open")))),
                       "url": reverse("usercommittee_workflow") + f"?stage={key}"})
    done_uc = sum(1 for r in ucr if r["completed"])
    active = [r for r in rows if not r["completed"]]
    active.sort(key=lambda r: (not r["overdue"], -(r["waiting"] or 0)))
    # वडागत सम्झौता स्थिति (कार्यप्रवाहका योजना)
    by_ward = {}
    for r in rows:
        w = by_ward.setdefault(r["ward"] or "पालिका", {"name": r["ward"] or "पालिका", "n": 0, "agreed": 0})
        w["n"] += 1
        w["agreed"] += r["agreed"] or r["completed"]
    def _wkey(w):
        t = str(w["name"]).translate(str.maketrans("०१२३४५६७८९", "0123456789"))
        return (w["name"] == "पालिका", int(t) if t.isdigit() else 999, t)

    wards_out = sorted(by_ward.values(), key=_wkey)
    for w in wards_out:
        w["pct"] = round(w["agreed"] * 100 / w["n"]) if w["n"] else 0
    audit_rows = [r for r in ucr if r["audit"] in ("done", "current", "warning", "pending") and r["agreed"]]
    audit_done = sum(1 for r in audit_rows if r["audit"] == "done")
    soon = sorted([r for r in active if r["days_left"] is not None and 0 <= r["days_left"] <= 15],
                  key=lambda r: r["days_left"])
    overdue = sorted([r for r in active if r["overdue"]], key=lambda r: -r["days_late"])
    methods = []
    for m in d["methods"]:
        n = m["n"] or 0
        methods.append(dict(m, done_pct=round((m["completed"]) * 100 / n) if n else 0))
    approvals = approvals_for(user, fy, wards, rows)
    return {
        "approvals": approvals[:6], "approval_count": len(approvals),
        "kpi": {
            "registered": projects.count(),
            "no_method": projects.filter(procurement_type__isnull=True).count(),
            "plan_draft": plans.filter(status="draft").count(),
            "committee": sum(1 for r in ucr if not r["completed"] and r["key"] == "committee"),
            "to_agree": sum(1 for r in rows if not r["completed"] and not r["agreed"]),
        },
        "stages": stages, "uc_total": len(ucr), "uc_done": done_uc,
        "uc_pct": round(done_uc * 100 / len(ucr)) if ucr else 0,
        "active": active[:8], "active_count": len(active),
        "wards": wards_out, "methods": methods,
        "audit": {"total": len(audit_rows), "done": audit_done, "pending": len(audit_rows) - audit_done,
                  "pct": round(audit_done * 100 / len(audit_rows)) if audit_rows else 0},
        "soon": soon[:5], "overdue": overdue[:5], "overdue_count": len(overdue),
    }


# ======================= साझा सहायक =======================
def _physical(ids):
    """योजना id -> पछिल्लो साइट फोटोको {pct, photo, at, lat, lng} (भौतिक प्रगति)."""
    from .models import ProjectTimeline

    out = {}
    for t in (ProjectTimeline.objects.filter(project_id__in=ids).order_by("project_id", "-created_at")
              .only("project_id", "image", "progress_pct", "created_at", "latitude", "longitude")):
        o = out.setdefault(t.project_id, {"pct": None, "photo": None, "at": t.created_at})
        if o["photo"] is None and t.image:
            o["photo"] = t.image.url
        if o["pct"] is None and t.progress_pct is not None:
            o["pct"] = t.progress_pct
    return out


def _projects(fy, wards):
    from .models import Project

    qs = Project.objects.filter(fiscalyear=fy) if fy else Project.objects.none()
    return qs if wards is None else qs.filter(ward_id__in=wards)


def _soon(active):
    return sorted([r for r in active if r["days_left"] is not None and 0 <= r["days_left"] <= 15],
                  key=lambda r: r["days_left"])


def _audit(ucr):
    rows = [r for r in ucr if r["audit"] in ("done", "current", "warning", "pending") and r["agreed"]]
    done = sum(1 for r in rows if r["audit"] == "done")
    return {"total": len(rows), "done": done, "pending": len(rows) - done,
            "pct": round(done * 100 / len(rows)) if rows else 0}


def _party(p, kind):
    """भुक्तानी पाउने: उपभोक्ता समिति / निर्माण व्यवसायी / फर्म."""
    try:
        if kind == "uc":
            uc = getattr(p, "user_committee", None)
            return uc.name if uc else ""
        if kind == "bid":
            from biddings.workflow import current_bid

            b = current_bid(p)
            return (b.bidder_name_nepali if b else "") or ""
        from quatation.workflow import current_quation

        q = current_quation(p)
        appr = getattr(q, "approval", None) if q else None
        return (appr.firm_name if appr else "") or ""
    except Exception:
        return ""


# ======================= लेखा अधिकृत =======================
PAY_STEP = {
    "final_tippani": ("भुक्तानी टिप्पणी बाँकी", "bg-rose-50 text-rose-700", 0),
    "sifaris_payment": ("वडा सिफारिस पर्खाइ", "bg-amber-50 text-amber-800", 1),
    "final": ("अन्तिम बिल / मूल्याङ्कन", "bg-indigo-50 text-indigo-700", 1),
    "valuation": ("अन्तिम मूल्याङ्कन", "bg-indigo-50 text-indigo-700", 2),
}


def _budget_heads(fy, wards, n=6):
    """बजेट उपशीर्षकअनुसार विनियोजन, खर्च, बाँकी (शीर्षक नभए स्रोतअनुसार)."""
    from .budget import usage
    from .models import BudgetHead

    projects = list(_projects(fy, wards).select_related("budget_head", "budget_type"))
    use = usage([p.id for p in projects])
    groups = {}
    has_heads = fy is not None and BudgetHead.objects.filter(fiscalyear=fy).exists()
    for p in projects:
        if has_heads:
            h = p.budget_head
            key = h.id if h else None
            g = groups.setdefault(key, {"code": h.code if h else "", "name": h.name if h else "शीर्षक नतोकिएका योजना",
                                        "head": D(h.allocated) if h and wards is None else None,
                                        "group": (h.budget_type.name if h and h.budget_type_id else ""),
                                        "budget": ZERO, "spent": ZERO, "n": 0})
        else:
            bt = p.budget_type
            g = groups.setdefault(bt.id if bt else None, {"code": "", "name": bt.name if bt else "स्रोत नतोकिएको",
                                                          "head": None, "group": "बजेट स्रोत", "budget": ZERO, "spent": ZERO, "n": 0})
        g["budget"] += D(p.budget)
        g["spent"] += use.get(p.id, {}).get("spent", ZERO)
        g["n"] += 1
    out = []
    for g in groups.values():
        alloc = g["head"] if g["head"] else g["budget"]
        g["allocated"] = alloc
        g["balance"] = alloc - g["spent"]
        g["pct"] = round(g["spent"] * 100 / alloc, 1) if alloc else 0
        out.append(g)
    out.sort(key=lambda g: (-g["allocated"]))
    return out[:n], len(out), has_heads


def D(v):
    return Decimal(str(v or 0))


def accounts(user, fy, wards, d):
    from .deductions import all_lines, retention_items
    from .models import Project

    rows = scan(user, wards)
    pay = [r for r in rows if not r["completed"] and r["key"] in PAY_STEP]
    pay.sort(key=lambda r: (PAY_STEP[r["key"]][2], -(r["waiting"] or 0)))
    objs = {p.id: p for p in Project.objects.filter(id__in=[r["id"] for r in pay[:10]]).select_related("user_committee")}
    for r in pay[:10]:
        r["step"], r["tone"], _ = PAY_STEP[r["key"]]
        r["party"] = _party(objs[r["id"]], r["kind"]) if r["id"] in objs else ""
    tippani = [r for r in pay if r["key"] == "final_tippani"]

    ids = list(_projects(fy, wards).values_list("id", flat=True))
    lines = all_lines(ids)
    taxes, ret_fy = {}, ZERO
    for ln in lines:
        if ln["retention"]:
            ret_fy += ln["amount"]
            continue
        t = taxes.setdefault(ln["code"], {"label": ln["label"], "amount": ZERO, "n": 0})
        t["amount"] += ln["amount"]
        t["n"] += 1
    tax_rows = sorted(taxes.values(), key=lambda t: -t["amount"])
    pq = Project.objects.all() if wards is None else Project.objects.filter(ward_id__in=wards)
    ret = [r for r in retention_items(list(pq.values_list("id", flat=True))) if r["status"] != "released"]
    from usercommittee.workflow import bs_date

    release = [r for r in ret if r["status"] in ("due", "recommended", "tippani")]
    release.sort(key=lambda r: ({"tippani": 0, "recommended": 1, "due": 2}[r["status"]], r["due"] or date.max))
    for r in release:
        r["due_bs"] = bs_date(r["due"]) if r["due"] else ""
    heads, heads_n, has_heads = _budget_heads(fy, wards)
    return {
        "pay": pay[:10], "pay_count": len(pay), "tippani_count": len(tippani),
        "tippani_amount": sum((r["budget"] for r in tippani), ZERO),
        "pay_amount": sum((r["budget"] for r in pay[:10]), ZERO),
        "taxes": tax_rows[:5], "tax_total": sum((t["amount"] for t in tax_rows), ZERO),
        "ret_fy": ret_fy, "ret_balance": sum((r["held"] for r in ret), ZERO), "ret_n": len(ret),
        "release": release[:3], "release_n": len(release),
        "release_amount": sum((r["held"] for r in release), ZERO),
        "heads": heads, "heads_n": heads_n, "has_heads": has_heads,
    }


# ======================= वडा अध्यक्ष / वडा सचिव =======================
def _ward_cat(r):
    if r["approve"]:
        return "approve"
    if r["key"] in ("sifaris_agreement", "sifaris_payment"):
        return "sifaris"
    if r["key"] == "public_audit":
        return "audit"
    if r["key"] in ("committee", "estimate"):
        return "committee"
    return "other"


CAT = {"approve": ("स्वीकृति", "bg-rose-50 text-rose-700", 0), "sifaris": ("सिफारिस", "bg-amber-50 text-amber-800", 1),
       "audit": ("सार्वजनिक परीक्षण", "bg-teal-50 text-teal-800", 2), "committee": ("समिति / लागत", "bg-indigo-50 text-indigo-700", 3),
       "other": ("कार्यान्वयन", "bg-slate-100 text-slate-600", 4)}


def ward(user, fy, wards, d):
    from usercommittee.models import UserCommittee

    from .budget import usage

    rows = scan(user, wards)
    active = [r for r in rows if not r["completed"]]
    for r in active:
        r["cat"] = _ward_cat(r)
        r["cat_label"], r["cat_tone"], r["cat_rank"] = CAT[r["cat"]]
    active.sort(key=lambda r: (r["cat_rank"], not r["overdue"], -(r["waiting"] or 0)))
    cats = [(k, v[0], sum(1 for r in active if r["cat"] == k)) for k, v in CAT.items()]
    ucr = [r for r in rows if r["kind"] == "uc"]
    formed = sum(1 for r in ucr if r["completed"] or r["key"] not in ("project", "committee"))
    phys = _physical([r["id"] for r in rows])
    pcts = [phys[r["id"]]["pct"] for r in active if r["agreed"] and r["id"] in phys and phys[r["id"]]["pct"] is not None]
    # योजना कार्ड: सम्झौता भएका चालु योजना (ठूलो बजेट पहिले), फोटो र भौतिक प्रगतिसहित
    projects = list(_projects(fy, wards).select_related("sector"))
    use = usage([p.id for p in projects])
    cards = sorted([r for r in active if r["agreed"]], key=lambda r: -r["budget"])[:4] or sorted(active, key=lambda r: -r["budget"])[:4]
    for r in cards:
        ph = phys.get(r["id"], {})
        r["photo"], r["pct"] = ph.get("photo"), ph.get("pct")
        r["spent"] = use.get(r["id"], {}).get("spent", ZERO)
    sectors = {}
    for p in projects:
        s = sectors.setdefault(p.sector_id, {"name": p.sector.name if p.sector_id else "क्षेत्र नतोकिएको",
                                             "budget": ZERO, "spent": ZERO, "n": 0})
        s["budget"] += D(p.budget)
        s["spent"] += use.get(p.id, {}).get("spent", ZERO)
        s["n"] += 1
    sectors = sorted(sectors.values(), key=lambda s: -s["budget"])
    for s in sectors:
        s["pct"] = round(s["spent"] * 100 / s["budget"], 1) if s["budget"] else 0
    ucs = (UserCommittee.objects.filter(project__in=projects).exclude(chairman_name="")
           .select_related("project").order_by("-id")[:4])
    return {
        "active": active[:12], "active_count": len(active), "cats": cats,
        "pending": sum(1 for r in active if r["cat"] in ("approve", "sifaris")),
        "approve_count": sum(1 for r in active if r["cat"] == "approve"),
        "sifaris_count": sum(1 for r in active if r["cat"] == "sifaris"),
        "uc_total": len(ucr), "uc_formed": formed, "uc_pct": round(formed * 100 / len(ucr)) if ucr else 0,
        "phys": round(sum(pcts) / len(pcts)) if pcts else None, "phys_n": len(pcts),
        "cards": cards, "sectors": sectors[:5], "audit": _audit(ucr), "soon": _soon(active)[:4],
        "overdue_count": sum(1 for r in active if r["overdue"]),
        "ucs": ucs, "uc_count": UserCommittee.objects.filter(project__in=projects).count(),
        "methods": [m for m in d["methods"] if m["n"]],
    }


# ======================= इन्जिनियर (पालिका / वडा) =======================
EST_KEYS = ("estimate", "notice", "invite")
VAL_KEYS = ("valuation", "final")


def engineer(user, fy, wards, d):
    from accounts.models import WardEngineer

    from .deductions import retention_items
    from .models import Project, ProjectTimeline

    rows = scan(user, wards)
    active = [r for r in rows if not r["completed"]]
    phys = _physical([r["id"] for r in rows])
    est = sorted([r for r in active if r["key"] in EST_KEYS or r.get("est_open")],
                 key=lambda r: (not r["overdue"], -(r["waiting"] or 0)))
    val = sorted([r for r in active if r["key"] in VAL_KEYS], key=lambda r: (not r["overdue"], -(r["waiting"] or 0)))
    for r in val + est[:6]:
        ph = phys.get(r["id"], {})
        r["pct"], r["photo_at"] = ph.get("pct"), ph.get("at")
    agreed = [r for r in active if r["agreed"]]
    from django.utils import timezone

    since = timezone.now() - timezone.timedelta(days=30)
    seen = sum(1 for r in agreed if r["id"] in phys and phys[r["id"]]["at"] and phys[r["id"]]["at"] >= since)
    photos = ProjectTimeline.objects.filter(project__fiscalyear=fy).exclude(image="").select_related(
        "project", "project__ward", "uploaded_by").order_by("-created_at")
    if wards is not None:
        photos = photos.filter(project__ward_id__in=wards)
    pq = Project.objects.all() if wards is None else Project.objects.filter(ward_id__in=wards)
    rec = [r for r in retention_items(list(pq.values_list("id", flat=True))) if r["status"] == "due"]
    staff = []
    if wards is None:
        per_ward = {}
        for r in active:
            per_ward[r["ward_id"]] = per_ward.get(r["ward_id"], 0) + 1
        for e in WardEngineer.objects.select_related("ward").order_by("ward_id"):
            staff.append({"name": e.name, "ward": e.ward.name, "mobile": e.mobile, "n": per_ward.get(e.ward_id, 0)})
    return {
        "total": len(rows), "active_count": len(active),
        "est": est[:6], "est_count": len(est), "val": val[:8], "val_count": len(val),
        "agreed": len(agreed), "seen": seen, "seen_pct": round(seen * 100 / len(agreed)) if agreed else 0,
        "overdue_count": sum(1 for r in active if r["overdue"]), "extended": 0,
        "photos": list(photos[:3]), "rec": rec[:4], "rec_count": len(rec), "staff": staff[:6],
        "soon": _soon(active)[:4],
    }
