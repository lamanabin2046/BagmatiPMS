"""मुख्य ड्यासबोर्ड — आ.व. अनुसार बजेट, खर्च, विधि/स्थिति, वडा, राजस्व र ध्यान दिनुपर्ने काम.

हिसाब खरिद तथा भुक्तानी प्रतिवेदनकै (usercommittee.reports.all_rows) — दुवैमा एउटै अङ्क।
क्रमागत योजनाको "यस आ.व. को खर्च" = कुल खर्च − अघिल्ला आ.व. मा खर्च (Project.spent_before)।
५ मिनेट cache; कुनै फारम सुरक्षित हुँदा (मेरो कामकै version) आफैँ छुट्छ।
"""
from collections import OrderedDict
from decimal import Decimal

from django.core.cache import cache
from django.db import connection

ZERO = Decimal("0")
CACHE_SECONDS = 300


def D(v):
    return Decimal(str(v or 0))


def pct(a, b):
    return round(D(a) * 100 / D(b), 1) if D(b) else 0


def _key(fy_id, wards):
    ver = cache.get(f"mywork:ver:{connection.schema_name}", 0)
    w = "all" if wards is None else "-".join(map(str, sorted(wards))) or "none"
    return f"dash:{connection.schema_name}:{ver}:{fy_id}:{w}"


def compute(fy, wards=None):
    key = _key(fy.id if fy else 0, wards)
    data = cache.get(key)
    if data is None:
        data = _compute(fy, wards)
        cache.set(key, data, CACHE_SECONDS)
    return data


def _compute(fy, wards):
    from accounts.models import Ward
    from usercommittee.reports import KINDS, STATUS, all_rows

    from .models import Project, RevenueSource

    projects = Project.objects.filter(fiscalyear=fy) if fy else Project.objects.none()
    if wards is not None:
        projects = projects.filter(ward_id__in=wards)
    ids = list(projects.values_list("id", flat=True))
    rows = all_rows(ids)
    seen = {r["p"].id for r in rows}
    before = dict(projects.values_list("id", "spent_before"))
    unassigned = [p for p in projects.select_related("ward") if p.id not in seen]

    # प्रति योजना एउटा पङ्क्ति (कुनै योजनाका एकभन्दा बढी हुन सक्छन्) — आवंटन एकपटक मात्र गनिने
    per = OrderedDict()
    for r in rows:
        x = per.setdefault(r["p"].id, {"p": r["p"], "kind": r["kind"], "status": r["status"], "allocated": D(r["allocated"]),
                                      "gross": ZERO, "contract": ZERO})
        x["gross"] += D(r["gross"])
        x["contract"] = max(x["contract"], D(r.get("contract")))
    for x in per.values():           # क्रमागत: अघिल्ला आ.व. को खर्च र आवंटन यस आ.व. मा नगनिने
        b = D(before.get(x["p"].id))
        x["this_year"] = max(x["gross"] - b, ZERO)
        x["allocated"] = max(x["allocated"] - b, ZERO)
    items = list(per.values())
    allocated = sum((x["allocated"] for x in items), ZERO) + sum((D(p.budget) for p in unassigned), ZERO)
    spent = sum((x["this_year"] for x in items), ZERO)
    spent_total = sum((x["gross"] for x in items), ZERO)
    committed = sum((max(x["contract"], x["gross"]) for x in items), ZERO)

    status = OrderedDict((k, {"label": v, "n": 0}) for k, v in STATUS.items())
    for x in items:
        status[x["status"]]["n"] += 1
    if unassigned:
        status["not_started"]["n"] += len(unassigned)

    methods = []
    for k, label in KINDS.items():
        xs = [x for x in items if x["kind"] == k]
        if not xs:
            continue
        a = sum((x["allocated"] for x in xs), ZERO)
        g = sum((x["this_year"] for x in xs), ZERO)
        methods.append({"kind": k, "label": label, "n": len(xs), "allocated": a, "spent": g, "pct": pct(g, a),
                        "completed": sum(1 for x in xs if x["status"] in ("completed", "paid")),
                        "running": sum(1 for x in xs if x["status"] == "running"),
                        "not_started": sum(1 for x in xs if x["status"] == "not_started")})

    ward_map = OrderedDict()
    for w in (Ward.objects.filter(id__in=wards) if wards is not None else Ward.objects.all()):
        ward_map[w.id] = {"name": w.name, "n": 0, "allocated": ZERO, "spent": ZERO, "completed": 0}
    ward_map[None] = {"name": "पालिका", "n": 0, "allocated": ZERO, "spent": ZERO, "completed": 0}
    for x in items:
        w = ward_map.setdefault(x["p"].ward_id, {"name": "?", "n": 0, "allocated": ZERO, "spent": ZERO, "completed": 0})
        w["n"] += 1
        w["allocated"] += x["allocated"]
        w["spent"] += x["this_year"]
        w["completed"] += x["status"] in ("completed", "paid")
    for p in unassigned:
        w = ward_map.setdefault(p.ward_id, {"name": "?", "n": 0, "allocated": ZERO, "spent": ZERO, "completed": 0})
        w["n"] += 1
        w["allocated"] += D(p.budget)
    wards_out = [dict(v, pct=pct(v["spent"], v["allocated"])) for v in ward_map.values() if v["n"]]
    try:
        wards_out.sort(key=lambda v: (v["name"] == "पालिका", int(str(v["name"]).strip() or 0)))
    except ValueError:
        pass

    # राजस्व
    from . import revenue as rv
    rev = {"n": 0, "est": ZERO, "contract": ZERO, "collected": ZERO, "outstanding": ZERO, "overdue": ZERO, "arrears": ZERO}
    rq = rv.queryset().filter(fiscalyear=fy) if fy else RevenueSource.objects.none()
    if wards is not None:
        rq = rq.filter(ward_id__in=wards)
    for s in rq:
        ms = rv.money_status(s)
        rev["n"] += 1
        rev["est"] += D(s.est_revenue)
        rev["contract"] += D(s.contract_amount)
        rev["collected"] += ms["paid"] + ms["late_paid"]
        if not s.settled_on:
            rev["outstanding"] += ms["outstanding"]
            rev["overdue"] += ms["overdue_amount"]
        rev["arrears"] += D(s.arrears)
    rev["pct"] = pct(rev["collected"], rev["contract"])

    trend = _trend(fy, rows)

    # धरौटी फिर्ता बाँकी (दायित्व)
    from .deductions import retention_items
    ret = [r for r in retention_items(ids) if r["status"] != "released"]
    return {
        "allocated": allocated, "spent": spent, "spent_total": spent_total, "committed": committed,
        "remaining": allocated - spent, "spent_pct": pct(spent, allocated),
        "committed_pct": pct(committed - (spent_total - spent), allocated),
        "count": len(items) + len(unassigned), "unassigned": len(unassigned), "status": status, "methods": methods,
        "wards": wards_out, "revenue": rev, "carried": sum(1 for v in before.values() if D(v)),
        "trend": trend,
        "retention": {"n": len(ret), "held": sum((r["held"] for r in ret), ZERO),
                      "due": sum(1 for r in ret if r["status"] in ("due", "recommended", "tippani"))},
    }


# ---------------------------------------------------------------- महिनावार भुक्तानी (आ.व. का १२ महिना)
FY_MONTHS = ["साउन", "भदौ", "असोज", "कात्तिक", "मंसिर", "पुस", "माघ", "फागुन", "चैत", "वैशाख", "जेठ", "असार"]


def _events(r):
    """एउटा योजनाका मिति भएका भुक्तानी [(मिति, रकम)] — जम्मा प्रतिवेदनको "कुल भुक्तानी" (gross) बराबर हुने गरी;
    अन्तिम भुक्तानीको रकम = कुल − अघिका किस्ता / अग्रिम / रनिङ."""
    p, k, gross = r["p"], r["kind"], D(r["gross"])
    ev, fin_date = [], None
    if k == "uc":
        ev = [(i.date, D(i.amount)) for i in p.installments.all()]
        fp = getattr(p, "final_payment", None)
        fin_date = fp.application_date if fp else None
    elif k == "bid":
        from biddings.workflow import contract_parts, current_bid
        from usercommittee.reports import BID_TAX

        _c, _b, _r, fin, advs, runs = contract_parts(current_bid(p))
        ev = [(a.approval_date, D(a.approved_amount)) for a in advs]
        ev += [(x.evaluation_date, D(x.net_payable) + sum((D(getattr(x, f, 0)) for f, _ in BID_TAX), ZERO)) for x in runs]
        fin_date = fin.payment_date if fin else None
    elif k == "quot":
        from quatation.workflow import current_quation, final_of

        q = current_quation(p)
        ev = [(a.approval_date, D(a.approved_amount)) for a in (q.advances.all() if q else [])]
        fin = final_of(q)
        fin_date = fin.application_date if fin else None
    else:
        from . import minor as mn

        m = mn.minor_of(p)
        ev = [(x.date, D(x.gross)) for x in (m.payments.all() if m else [])]
    rest = gross - sum((a for _, a in ev), ZERO)
    if rest > 1:
        d = fin_date or max((d for d, _ in ev if d), default=None)
        if d:
            ev.append((d, rest))
    return [(d, a) for d, a in ev if d and a]


def _trend(fy, rows):
    """आ.व. का साउन–असार महिनाअनुसार भुक्तानी, विधिअनुसार छुट्टाछुट्टै."""
    from nepali.date_converter import converter
    from usercommittee.reports import KINDS

    try:
        y0 = int(str(fy.name).split("/")[0]) if fy else None
    except ValueError:
        y0 = None
    out = {k: [0.0] * 12 for k in KINDS}
    if y0 is None:
        return {"labels": FY_MONTHS, "series": []}
    undated = outside = 0.0
    for r in rows:
        ev = _events(r)
        undated += max(float(D(r["gross"]) - sum((a for _, a in ev), ZERO)), 0.0)
        for d, amt in ev:
            try:
                y, m, _dd = converter.english_to_nepali(d.year, d.month, d.day)
            except Exception:
                continue
            i = m - 4 if y == y0 and m >= 4 else (m + 8 if y == y0 + 1 and m <= 3 else None)
            if i is not None:
                out[r["kind"]][i] += float(amt)
            else:
                outside += float(amt)
    series = [{"kind": k, "label": label, "data": out[k]} for k, label in KINDS.items() if any(out[k])]
    # undated: भुक्तानी मिति नभरिएको; outside: अर्को आ.व. को मितिमा (क्रमागत / पछि प्रविष्ट)
    return {"labels": FY_MONTHS, "series": series, "total": [sum(s["data"][i] for s in series) for i in range(12)],
            "undated": round(undated, 2), "outside": round(outside, 2)}
