"""मेरो काम — लगइन गर्ने व्यक्तिलाई अहिले के गर्नुपर्ने छ भन्ने सूची (भूमिका / अनुमति र वडाअनुसार).

स्रोत:
  * उपभोक्ता समिति / बोलपत्र / दरभाउपत्र कार्यप्रवाह — स्वीकृति बाँकी, म्याद नाघेको, र हालको चरण
    (त्यो चरण गर्ने अनुमति भएका व्यक्तिलाई मात्र)
  * बैंक ग्यारेन्टी — म्याद सकिएका / ३० दिनभित्र सकिने (PG, APG)
  * धरौटी फिर्ता — सिफारिस बाँकी, टिप्पणी / फिर्ता बाँकी
  * बजेट — विनियोजनभन्दा बढी खर्च / प्रतिबद्धता, बजेट शीर्षक नतोकिएका योजना

हिसाब भारी भएकाले प्रति प्रयोगकर्ता केही समय cache गरिन्छ (CACHE_SECONDS)।
"""
from django.core.cache import cache
from django.db import connection
from django.urls import reverse

from .permissions import user_perms

CACHE_SECONDS = 60

# कार्यप्रवाहको हालको चरण → त्यो चरण गर्ने अनुमति (कुनै एक भए पुग्छ)
UC_STEP_PERMS = {
    "committee": {"uc.committee"},
    "estimate": {"uc.estimate"},
    "sifaris_agreement": {"uc.sifaris_upload"},
    "agreement": {"uc.agreement_print"},
    "valuation": {"uc.valuation"},
    "public_audit": {"uc.public_audit"},
    "sifaris_payment": {"uc.sifaris_upload"},
    "final_tippani": {"uc.payment_print"},
    "handover": {"uc.payment_print"},
}
BID_STEP_PERMS = {
    "notice": {"bid.manage"}, "evaluation": {"bid.manage"}, "intent": {"bid.print"},
    "acceptance": {"bid.manage"}, "agreement": {"bid.manage"}, "final": {"bid.manage"},
    "final_tippani": {"bid.print"},
}
QUOT_STEP_PERMS = {
    "invite": {"quot.manage"}, "invite_letter": {"quot.print"}, "quotes": {"quot.manage"},
    "agreement": {"quot.manage"}, "final": {"quot.manage"}, "final_tippani": {"quot.print"},
}
TONES = {"urgent": 0, "warn": 1, "todo": 2, "info": 3}


def _wards(user):
    from usercommittee.views_workflow import _user_wards

    return _user_wards(user)


def _cur(qs):
    """कार्यप्रवाहका बाँकी काम: चालु आ.व. का योजना मात्र (अघिल्ला आ.व. का हेर्न मात्र)।"""
    from projects.fiscal import current_fy_id

    cid = current_fy_id()
    return qs.filter(fiscalyear_id=cid) if cid else qs


def _item(group, label, count, url, tone="todo", icon="fa-circle-dot", hint=""):
    return {"group": group, "label": label, "count": count, "url": url, "tone": tone, "icon": icon, "hint": hint}


def _workflow_items(user, P, wards):
    items = []
    mods = []
    if any(p.startswith("uc.") for p in P):
        from usercommittee import workflow as uc

        mods.append(("उपभोक्ता समिति", reverse("usercommittee_workflow"), _cur(uc.workflow_queryset()), uc.STEP_INFO, UC_STEP_PERMS,
                     lambda p: uc.project_workflow(p, user.user_type, user),
                     lambda p, s: s["current_key"] == "approval" and uc.can_approve(user, p, s["mode"]),
                     bool(P & {"uc.committee", "uc.estimate", "uc.valuation", "project.manage", "uc.approve"})))
    if "bid.view" in P:
        from biddings import workflow as bw

        ok = bw.can_approve(user)
        mods.append(("बोलपत्र ठेक्का", reverse("bid_workflow"), _cur(bw.workflow_queryset()), bw.STEP_INFO, BID_STEP_PERMS,
                     lambda p: bw.bid_workflow(p, user), lambda p, s, ok=ok: ok and s["current_key"] == "approval",
                     bool(P & {"bid.manage", "bid.approve"})))
    if "quot.view" in P:
        from quatation import workflow as qw

        ok = qw.can_approve(user)
        mods.append(("दरभाउपत्र खरिद", reverse("quot_workflow"), _cur(qw.workflow_queryset()), qw.STEP_INFO, QUOT_STEP_PERMS,
                     lambda p: qw.quot_workflow(p, user), lambda p, s, ok=ok: ok and s["current_key"] == "approval",
                     bool(P & {"quot.manage", "quot.approve"})))
    for label, url, qs, info, step_perms, wf, waiting, cares_overdue in mods:
        if wards is not None:
            qs = qs.filter(ward_id__in=wards)
        approve = overdue = 0
        steps = {}
        for p in qs:
            _st, s = wf(p)
            if s["completed"]:
                continue
            if waiting(p, s):
                approve += 1
            else:
                # हालको चरण (+ उपभोक्ता समितिमा: समिति बाँकी हुँदा लागत अनुमान पनि — जुनसुकै क्रम)
                keys = {s["current_key"]}
                if s["current_key"] == "committee":
                    keys |= {x["key"] for x in _st if x["key"] == "estimate" and x["state"] != "done"}
                for k in keys:
                    if P & step_perms.get(k, set()):
                        steps[k] = steps.get(k, 0) + 1
            if s.get("overdue"):
                overdue += 1
        if approve:
            items.append(_item(label, "रुजु / स्वीकृति बाँकी", approve, url + "?stage=to_approve", "urgent", "fa-stamp"))
        if overdue and cares_overdue:
            items.append(_item(label, "काम सम्पन्न गर्ने म्याद नाघेको", overdue, url + "?stage=overdue", "warn", "fa-clock"))
        for key in info:
            if steps.get(key):
                items.append(_item(label, info[key][1], steps[key], url + f"?stage={key}", "todo", "fa-arrow-right",
                                   "हालको चरण"))
    return items


def _minor_items(P, wards):
    if not P & {"minor.view", "minor.manage", "minor.approve"}:
        return []
    from projects import minor as mn

    qs = _cur(mn.workflow_queryset())
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    url = reverse("minor_list")
    approve, overdue, steps = {}, {}, {}
    for p in qs:
        if mn.method_of(p) == "sanstha":
            continue          # तल _sanstha_items
        _st, s = mn.workflow(p)
        if s["completed"] or not s["current_key"]:
            continue
        meth, key = s["method"], s["current_key"]
        if key == "approval" and "minor.approve" in P:
            approve[meth] = approve.get(meth, 0) + 1
        elif mn.STEP_PERMS.get(key) in P and key != "plan":
            steps[(meth, key)] = steps.get((meth, key), 0) + 1
        if s["overdue"] and "minor.manage" in P:
            overdue[meth] = overdue.get(meth, 0) + 1
    items = []
    for meth, n in approve.items():
        items.append(_item(mn.METHOD_LABEL[meth], "छनौट / स्वीकृति बाँकी", n, f"{url}?method={meth}&stage=to_approve",
                           "urgent", "fa-stamp"))
    for meth, n in overdue.items():
        items.append(_item(mn.METHOD_LABEL[meth], "सम्पन्न गर्ने म्याद नाघेको", n, f"{url}?method={meth}&stage=overdue",
                           "warn", "fa-clock"))
    for (meth, key), n in sorted(steps.items(), key=lambda kv: (kv[0][0], mn.STEPS[kv[0][0]].index(kv[0][1]))):
        items.append(_item(mn.METHOD_LABEL[meth], mn.label(key, meth), n, f"{url}?method={meth}&stage={key}", "todo",
                           "fa-arrow-right", "हालको चरण"))
    return items


def _backup_items(P):
    if "backup.manage" not in P:
        return []
    from projects import backup

    age = backup.latest_age_hours(connection.schema_name)
    if age is not None and age <= 48:
        return []
    return [_item("सेटिङ", "ब्याकअप " + ("भएको छैन" if age is None else f"{int(age // 24)} दिनदेखि भएको छैन"), 1,
                  reverse("backups"), "warn", "fa-database")]


def _revenue_items(P, wards):
    if not P & {"rev.view", "rev.manage", "rev.approve", "rev.collect", "rev.survey"}:
        return []
    from projects import revenue as rv

    qs = rv.queryset().exclude(status__in=["completed"])
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    url = reverse("revenue_list")
    c = {"approve": 0, "overdue": 0, "soon": 0, "sign": 0, "env": 0, "qty": 0}
    for s in qs:
        if s.settled_on:
            continue
        _st, sm = rv.workflow(s)
        if sm["current_key"] in ("approval", "award") and "rev.approve" in P:
            c["approve"] += 1
        ms = sm["money"]
        if not s.cancelled_on:
            c["overdue"] += bool(ms["overdue"])
            c["soon"] += bool(ms["soon"])
        c["sign"] += sm["sign_overdue"]
        c["env"] += bool(rv.env_expiring(s))
        c["qty"] += bool(ms["extracted_pct"] is not None and ms["extracted_pct"] >= 80)
    items = []
    G = "राजस्व आम्दानी"
    if c["approve"]:
        items.append(_item(G, "स्वीकृति बाँकी (प्रशासनिक / सफल बोलपत्रदाता)", c["approve"], f"{url}?stage=to_approve", "urgent", "fa-stamp"))
    if c["overdue"] and P & {"rev.collect", "rev.manage"}:
        items.append(_item(G, "किस्ता म्याद नाघेको — ताकेता / विलम्ब शुल्क", c["overdue"], f"{url}?stage=overdue", "urgent", "fa-bell"))
    if c["soon"] and P & {"rev.collect", "rev.manage"}:
        items.append(_item(G, "किस्ता बुझाउने म्याद नजिकिँदै", c["soon"], f"{url}?stage=collection", "todo", "fa-clock"))
    if c["sign"] and P & {"rev.approve", "rev.manage"}:
        items.append(_item(G, "स्वीकृत बोलपत्रदाताले सम्झौता नगरेको", c["sign"], f"{url}?stage=agreement", "warn", "fa-user-xmark"))
    if c["env"]:
        items.append(_item(G, "वातावरणीय स्वीकृति सकिन लागेको", c["env"], url, "warn", "fa-leaf"))
    if c["qty"]:
        items.append(_item(G, "स्वीकृत उत्खनन परिमाणको ८०% नाघेको", c["qty"], url, "warn", "fa-truck"))
    return items


def _sanstha_items(P, wards):
    from projects import sanstha as sn

    qs = _cur(sn.workflow_queryset())
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    url = reverse("sanstha_workflow")
    approve = overdue = 0
    steps = {}
    need = {"invite": "minor.manage", "proposals": "minor.manage", "agreement": "minor.manage", "completion": "minor.manage",
            "final": "minor.manage", "invite_letter": "minor.print", "final_tippani": "minor.print"}
    for p in qs:
        _st, s = sn.workflow(p)
        key = s["current_key"]
        if s["completed"] or not key:
            continue
        if key == "approval" and "minor.approve" in P:
            approve += 1
        elif need.get(key) in P:
            steps[key] = steps.get(key, 0) + 1
        if s["overdue"] and "minor.manage" in P:
            overdue += 1
    items = []
    if approve:
        items.append(_item(sn.LABEL, "प्रस्ताव छनौट / स्वीकृति बाँकी", approve, f"{url}?stage=to_approve", "urgent", "fa-stamp"))
    if overdue:
        items.append(_item(sn.LABEL, "सम्झौता म्याद नाघेको", overdue, f"{url}?stage=overdue", "warn", "fa-clock"))
    for key in sn.STEPS:
        if steps.get(key):
            items.append(_item(sn.LABEL, sn.STEP_INFO[key][1], steps[key], f"{url}?stage={key}", "todo", "fa-arrow-right",
                               "हालको चरण"))
    return items


def _guarantee_items(P, wards):
    if not P & {"bid.view", "quot.view"}:
        return []
    from projects.views_guarantees import apg_rows, pg_rows

    items = []
    for which, rows, name, perm in (("pg", pg_rows if "bid.view" in P else None, "Performance Guarantee (PG)", "performance_guarantees"),
                                    ("apg", apg_rows, "Advance Payment Guarantee (APG)", "advance_guarantees")):
        if rows is None:
            continue
        rs = [r for r in rows() if wards is None or r["p"].ward_id in wards]
        if which == "apg" and "quot.view" not in P:
            rs = [r for r in rs if r["kind"] == "bid"]
        if which == "apg" and "bid.view" not in P:
            rs = [r for r in rs if r["kind"] == "quot"]
        expired = sum(1 for r in rs if r["status"] == "expired")
        expiring = sum(1 for r in rs if r["status"] == "expiring")
        url = reverse(perm)
        if expired:
            items.append(_item("बैंक ग्यारेन्टी", f"{name} — म्याद सकिएको", expired, url + "?status=expired", "urgent",
                               "fa-circle-xmark", "नवीकरण वा जफत गर्ने निर्णय"))
        if expiring:
            items.append(_item("बैंक ग्यारेन्टी", f"{name} — ३० दिनभित्र सकिने", expiring, url + "?status=expiring", "warn",
                               "fa-hourglass-half", "म्याद थपका लागि बैंकलाई पत्र"))
    return items


def _retention_items(P, wards):
    rec, man = "retention.recommend" in P, "retention.manage" in P
    if not (rec or man):
        return []
    from projects.deductions import retention_items
    from projects.models import Project

    ids = Project.objects.all()
    if wards is not None:
        ids = ids.filter(ward_id__in=wards)
    its = retention_items(list(ids.values_list("id", flat=True)))
    url = reverse("retention_list")
    items = []
    due = sum(1 for i in its if i["status"] == "due")
    if due and rec:
        items.append(_item("धरौटी फिर्ता", "फिर्ता योग्य — सिफारिस अपलोड गर्न बाँकी", due, url + "?status=due", "todo", "fa-file-arrow-up"))
    if man:
        n = sum(1 for i in its if i["status"] == "recommended")
        if n:
            items.append(_item("धरौटी फिर्ता", "सिफारिस आएको — टिप्पणी बाँकी", n, url + "?status=recommended", "todo", "fa-file-signature"))
        n = sum(1 for i in its if i["status"] == "tippani")
        if n:
            items.append(_item("धरौटी फिर्ता", "टिप्पणी भएको — फिर्ता दर्ता बाँकी", n, url + "?status=tippani", "todo", "fa-money-bill-transfer"))
    return items


def _budget_items(P, wards):
    if not P & {"budget.view", "budget.manage"}:
        return []
    from projects.budget import TOL, D, usage
    from projects.models import BudgetHead, FiscalYear, Project

    from projects.fiscal import current_fy

    fy = current_fy()
    if fy is None:
        return []
    qs = Project.objects.filter(fiscalyear=fy)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    projects = list(qs.only("id", "budget", "budget_head_id"))
    use = usage([p.id for p in projects])
    over = 0
    for p in projects:
        u = use.get(p.id)
        if u and D(p.budget) > 0 and (u["spent"] > D(p.budget) + TOL or u["committed"] > D(p.budget) + TOL):
            over += 1
    base = reverse("budget_status") + f"?fiscalyear={fy.id}"
    items = []
    if over:
        items.append(_item("बजेट", "विनियोजनभन्दा बढी खर्च / सम्झौता भएका योजना", over, base + "&flag=over", "warn",
                           "fa-triangle-exclamation", "बजेट थप / रकमान्तर चाहिन्छ"))
    if "budget.manage" in P and BudgetHead.objects.filter(fiscalyear=fy).exists():
        n = sum(1 for p in projects if not p.budget_head_id)
        if n:
            items.append(_item("बजेट", f"बजेट शीर्षक नतोकिएका योजना ({fy.name})", n,
                               reverse("budget_heads") + f"?fiscalyear={fy.id}", "info", "fa-tags"))
    return items


def _app_items(P, wards):
    if not P & {"app.manage", "app.approve"}:
        return []
    from projects.models import FiscalYear, ProcurementPlan, Project

    from projects.fiscal import current_fy

    fy = current_fy()
    if fy is None:
        return []
    items = []
    base = reverse("app_list") + f"?fiscalyear={fy.id}"
    if "app.approve" in P:
        qs = ProcurementPlan.objects.filter(project__fiscalyear=fy, status="draft")
        if wards is not None:
            qs = qs.filter(project__ward_id__in=wards)
        n = qs.count()
        if n:
            items.append(_item("वार्षिक खरिद योजना", "खरिद योजना स्वीकृत गर्न बाँकी", n, base + "&status=draft", "urgent",
                               "fa-check-double"))
    if "app.manage" in P:
        qs = Project.objects.filter(fiscalyear=fy, procurement_type__isnull=True)
        if wards is not None:
            qs = qs.filter(ward_id__in=wards)
        n = qs.count()
        if n:
            items.append(_item("वार्षिक खरिद योजना", "खरिद विधि तोक्न बाँकी योजना", n, base + "&status=none", "todo",
                               "fa-list-check", "दर्ता भएका तर विधि नतोकिएका"))
    return items


def compute(user):
    P = user_perms(user)
    wards = _wards(user)
    items = (_app_items(P, wards) + _workflow_items(user, P, wards) + _minor_items(P, wards) + _guarantee_items(P, wards) + _retention_items(P, wards)
             + _budget_items(P, wards) + _sanstha_items(P, wards) + _revenue_items(P, wards) + _backup_items(P))
    items.sort(key=lambda i: TONES[i["tone"]])
    return {"items": items, "total": sum(i["count"] for i in items),
            "urgent": sum(i["count"] for i in items if i["tone"] == "urgent")}


def _schema():
    return getattr(connection, "schema_name", "public")


def _key(user):
    # पालिकामा कुनै पनि फारम सुरक्षित हुँदा version बदलिन्छ → सबैको पुरानो cache आफैँ छुट्छ
    ver = cache.get(f"mywork:ver:{_schema()}", 0)
    return f"mywork:{_schema()}:{ver}:{user.pk}"


def bump():
    """कुनै काम भएपछि (POST) — यस पालिकाका सबैको 'मेरो काम' फेरि हिसाब गर्ने."""
    key = f"mywork:ver:{_schema()}"
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, None)


class MyWorkInvalidateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method == "POST" and response.status_code < 400 and getattr(request, "user", None) \
                and request.user.is_authenticated:
            bump()
        return response


def my_work(user, fresh=False):
    key = _key(user)
    data = None if fresh else cache.get(key)
    if data is None:
        data = compute(user)
        cache.set(key, data, CACHE_SECONDS)
    return data


def forget(user):
    cache.delete(_key(user))
