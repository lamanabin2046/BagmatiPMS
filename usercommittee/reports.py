"""खरिद तथा भुक्तानी प्रतिवेदन — उपभोक्ता समिति, बोलपत्र ठेक्का र दरभाउपत्र खरिद, सबै एउटै ढाँचामा
(विनियोजित, लागत अनुमान, सम्झौता, भुक्तानी, कर कट्टी) र एकीकृत सारांश.

उपभोक्ता समिति:

भुक्तानी (कुल):  अन्तिम मूल्याङ्कन भए FinalPayment.office_contribution (किस्ता समेत),
                 नभए दिइसकेका किस्ताको जम्मा।
कर कट्टी:        अन्तिम भुक्तानीको कर + हरेक किस्ताको कर (शीर्षकअनुसार)।
खुद भुक्तानी:    कुल भुक्तानी − कर।
सम्पन्न:          workflow का सबै चरण पूरा (हस्तान्तरणसम्म)।
"""
from collections import OrderedDict
from decimal import Decimal

ZERO = Decimal("0")
STATUS = OrderedDict([
    ("completed", "सम्पन्न"),
    ("paid", "अन्तिम बिल भएको"),
    ("running", "चालु"),
    ("not_started", "प्रक्रिया सुरु नभएको"),
])
KINDS = OrderedDict([("uc", "उपभोक्ता समिति"), ("bid", "बोलपत्र ठेक्का"), ("quot", "दरभाउपत्र खरिद"),
                     ("direct", "सोझै खरिद"), ("amanat", "अमानत"), ("sanstha", "संस्था / समिति")])
MINOR_KINDS = ("direct", "amanat", "sanstha")
KIND_PTYPE = {"uc": 1, "bid": 2, "quot": 3}       # Project.procurement_type_id
# बोलपत्र / दरभाउपत्रका निश्चित कट्टी → कर शीर्षक code (उपभोक्ता समितिका शीर्षकसँगै जोडिन्छ)
EXTRA_LABELS = {"vat": "मूल्य अभिवृद्धि कर (भ्याट) कट्टी", "dharauti": "धरौटी / रिटेन्सन कट्टी", "ld": "ढिलाइ हर्जाना"}


def D(v):
    return Decimal(str(v or 0))


def as_dict(v):
    """tax_deduction — पुराना अभिलेखमा text भए पनि dict."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        import json
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _status(project, summary):
    if summary["completed"]:
        return "completed"
    if getattr(project, "final_payment", None) is not None:
        return "paid"
    if getattr(project, "user_committee", None) is None:
        return "not_started"
    return "running"


def project_rows(qs, status=""):
    """हरेक योजनाको रकम र स्थिति। status दिए त्यही स्थितिका मात्र।"""
    from .workflow import project_workflow

    rows = []
    for p in qs:
        _steps, summary = project_workflow(p)
        st = _status(p, summary)
        if status and st != status:
            continue
        uc = getattr(p, "user_committee", None)
        est = getattr(p, "cost_estimate", None)
        fp = getattr(p, "final_payment", None)
        insts = list(p.installments.all())
        inst_amount = sum((i.amount for i in insts), ZERO)
        taxes = {}
        for src in ([fp.tax_deduction] if fp else []) + [i.tax_deduction for i in insts]:
            for code, v in as_dict(src).items():
                taxes[code] = taxes.get(code, ZERO) + D(v)
        gross = D(fp.office_contribution) if fp else inst_amount
        tax = sum(taxes.values(), ZERO)
        allocated = D(p.budget)
        rows.append({
            "p": p, "uc": uc, "kind": "uc", "kind_label": KINDS["uc"], "party": uc.name if uc else "",
            "contract": D(est.total_cost) if est else None,
            "status": st, "status_label": STATUS[st],
            "allocated": allocated,
            "estimate": D(est.total_cost) if est else None,
            "office_share": (D(est.budget) - D(est.contingency_amount)) if est else None,
            "contingency": D(est.contingency_amount) if est else ZERO,
            "user_share": D(est.user_contribution) if est else ZERO,
            "valuation": D(fp.final_evaluation) if fp else None,
            "installments": inst_amount, "inst_count": len(insts),
            "gross": gross, "tax": tax, "taxes": taxes, "net": gross - tax,
            "remaining": allocated - gross,
            "work_category": p.work_category.name if p.work_category_id else "",
        })
    return rows


def totals(rows):
    keys = ("allocated", "contingency", "user_share", "installments", "gross", "tax", "net", "remaining")
    t = {k: sum((r[k] for r in rows), ZERO) for k in keys}
    t["contract"] = sum((r["contract"] for r in rows if r.get("contract") is not None), ZERO)
    t["estimate"] = sum((r["estimate"] for r in rows if r["estimate"] is not None), ZERO)
    t["office_share"] = sum((r["office_share"] for r in rows if r["office_share"] is not None), ZERO)
    t["valuation"] = sum((r["valuation"] for r in rows if r["valuation"] is not None), ZERO)
    t["count"] = len(rows)
    t["by_status"] = OrderedDict((k, sum(1 for r in rows if r["status"] == k)) for k in STATUS)
    t["paid_pct"] = round(t["gross"] * 100 / t["allocated"], 1) if t["allocated"] else 0
    return t


def by_ward(rows, wards):
    out = []
    for w in wards:
        rs = [r for r in rows if r["p"].ward_id == w.id]
        if rs:
            out.append({"ward": w, **totals(rs)})
    other = [r for r in rows if r["p"].ward_id not in {w.id for w in wards}]
    if other:
        out.append({"ward": None, **totals(other)})
    return out


def by_tax_head(rows, wards):
    """[{"code", "name", "total", "count", "ward_values": [...], "projects": [(row, amount)]}] — शीर्षकअनुसार।"""
    from .tax import tax_labels

    labels = {**EXTRA_LABELS, **tax_labels()}
    order = {}
    try:
        from .models import TaxHead
        order = {h.code: (h.sort, h.id) for h in TaxHead.objects.all()}
    except Exception:
        pass
    heads = {}
    for r in rows:
        for code, v in r["taxes"].items():
            h = heads.setdefault(code, {"code": code, "name": labels.get(code, code), "total": ZERO,
                                        "projects": [], "by_ward": {}})
            h["total"] += v
            h["projects"].append((r, v))
            h["by_ward"][r["p"].ward_id] = h["by_ward"].get(r["p"].ward_id, ZERO) + v
    out = sorted(heads.values(), key=lambda h: order.get(h["code"], (999, h["name"])))
    for h in out:
        h["count"] = len(h["projects"])
        h["ward_values"] = [h["by_ward"].get(w.id) for w in wards]
    return out


# ---------------------------------------------------------------- बोलपत्र ठेक्का
def _gen_status(summary, has_final, started):
    if summary["completed"]:
        return "completed"
    if has_final:
        return "paid"
    return "running" if started else "not_started"


BID_TAX = (("agrim_tax", "agrim_tax"), ("vat_deduction", "vat"), ("dharauti_deduction", "dharauti"), ("bahal_tax", "bahal_tax"),
           ("ld_amount", "ld"))


def bid_rows(qs, status=""):
    """बोलपत्र: कुल भुक्तानी = दिइसकेको नगद (अग्रिम + रनिङ खुद + अन्तिम खुद) + कट्टी (कर, धरौटी)।
    अन्तिम बिल भएपछि यो कुल मूल्याङ्कन रकम बराबर हुन्छ।"""
    from biddings.workflow import bid_workflow, contract_parts, current_bid

    rows = []
    for p in qs:
        _steps, summary = bid_workflow(p)
        bid = current_bid(p)
        _c, _bond, _req, fin, advances, runs = contract_parts(bid)
        st = _gen_status(summary, fin is not None, bid is not None)
        if status and st != status:
            continue
        taxes = {}
        for src in runs + ([fin] if fin else []):
            for field, code in BID_TAX:
                v = D(getattr(src, field, 0))
                if v:
                    taxes[code] = taxes.get(code, ZERO) + v
        adv = sum((D(a.approved_amount) for a in advances), ZERO)
        cash = adv + sum((D(r.net_payable) for r in runs), ZERO) + (D(fin.final_amount) if fin else ZERO)
        tax = sum(taxes.values(), ZERO)
        gross = cash + tax
        allocated = D(p.budget)
        rows.append({
            "p": p, "uc": None, "kind": "bid", "kind_label": KINDS["bid"],
            "party": (bid.bidder_name_nepali or "") if bid else "",
            "status": st, "status_label": STATUS[st], "allocated": allocated,
            "estimate": D(bid.total_cost_estimate) if bid and bid.total_cost_estimate else None,
            "contract": D(bid.bidding_amount) if bid and bid.bidding_amount else None,
            "office_share": None, "contingency": D(bid.contingency_amount) if bid else ZERO, "user_share": ZERO,
            "valuation": D(fin.total_evaluation_amount) if fin else None,
            "installments": adv + sum((D(r.payable_amount) - D(r.advance_adjusted) for r in runs), ZERO),
            "inst_count": len(advances) + len(runs),
            "gross": gross, "tax": tax, "taxes": taxes, "net": cash, "remaining": allocated - gross,
            "work_category": p.work_category.name if p.work_category_id else "",
        })
    return rows


# ---------------------------------------------------------------- दरभाउपत्र खरिद
def quot_rows(qs, status=""):
    """दरभाउपत्र: कुल भुक्तानी = अग्रिम + अन्तिम खुद + कट्टी (आयकर, धरौटी)।"""
    from quatation.workflow import current_quation, final_of, lowest, quot_workflow

    rows = []
    for p in qs:
        _steps, summary = quot_workflow(p)
        q = current_quation(p)
        fin = final_of(q)
        st = _gen_status(summary, fin is not None, q is not None)
        if status and st != status:
            continue
        advances = list(q.advances.all()) if q else []
        taxes = {}
        if fin:
            for code, v in (("agrim_tax", fin.taxdeduction), ("dharauti", fin.retension)):
                if v:
                    taxes[code] = taxes.get(code, ZERO) + D(v)
        adv = sum((D(a.approved_amount) for a in advances), ZERO)
        cash = adv + (D(fin.finalpayment) if fin else ZERO)
        tax = sum(taxes.values(), ZERO)
        gross = cash + tax
        allocated = D(p.budget)
        appr = getattr(q, "approval", None) if q else None
        firm, price = lowest(q) if q else (None, None)
        rows.append({
            "p": p, "uc": None, "kind": "quot", "kind_label": KINDS["quot"],
            "party": (appr.firm_name if appr and appr.firm_name else firm) or "",
            "status": st, "status_label": STATUS[st], "allocated": allocated,
            "estimate": D(q.cost_estimate) if q else None,
            "contract": D(appr.amount) if appr and appr.amount else (D(price) if price else None),
            "office_share": None, "contingency": D(q.contingency) if q and q.contingency else ZERO, "user_share": ZERO,
            "valuation": D(fin.totalValuation) if fin and fin.totalValuation is not None else None,
            "installments": adv, "inst_count": len(advances),
            "gross": gross, "tax": tax, "taxes": taxes, "net": cash, "remaining": allocated - gross,
            "work_category": p.work_category.name if p.work_category_id else "",
        })
    return rows


# ---------------------------------------------------------------- सोझै खरिद / अमानत / संस्था
def minor_rows(qs, status=""):
    """कुल भुक्तानी = सबै भुक्तानी (हाजिरी, किस्ता, अन्तिम) को कुल रकम; कर = कट्टी (आयकर, भ्याट, धरौटी)."""
    from projects import minor as mn

    rows = []
    for p in qs:
        _steps, summary = mn.workflow(p)
        m = mn.minor_of(p)
        fin = mn.final_payment(m)
        st = _gen_status(summary, fin is not None, m is not None)
        if status and st != status:
            continue
        kind = summary["method"]
        pays = list(m.payments.all()) if m else []
        taxes = {}
        for pay in pays:
            for code, v in (pay.taxes or {}).items():
                if D(v):
                    taxes[code] = taxes.get(code, ZERO) + D(v)
        gross = sum((D(x.gross) for x in pays), ZERO)
        tax = sum(taxes.values(), ZERO)
        allocated = D(p.budget)
        running = [x for x in pays if x.kind != "final"]
        rows.append({
            "p": p, "uc": None, "kind": kind, "kind_label": KINDS[kind],
            "party": (m.selected.name if m and m.selected else (m.in_charge if m else "")) or "",
            "status": st, "status_label": STATUS[st], "allocated": allocated,
            "estimate": D(m.estimate_amount) if m else None,
            "contract": D(m.order_amount) if m and m.order_amount else None,
            "office_share": None, "contingency": ZERO, "user_share": ZERO,
            "valuation": D(m.completion_value) if m and m.completion_value else None,
            "installments": sum((D(x.gross) for x in running), ZERO), "inst_count": len(running),
            "gross": gross, "tax": tax, "taxes": taxes, "net": gross - tax, "remaining": allocated - gross,
            "work_category": p.work_category.name if p.work_category_id else "",
        })
    return rows


def all_rows(project_ids, kind="", status=""):
    """सबै विधिका पङ्क्ति (क्रम: वडा, नाम). kind: '' | uc | bid | quot."""
    from biddings.workflow import workflow_queryset as bid_qs
    from quatation.workflow import workflow_queryset as quot_qs

    from .workflow import workflow_queryset as uc_qs

    rows = []
    if kind in ("", "uc"):
        rows += project_rows(uc_qs().filter(id__in=project_ids).select_related("work_category"), status)
    if kind in ("", "bid"):
        rows += bid_rows(bid_qs().filter(id__in=project_ids).select_related("work_category"), status)
    if kind in ("", "quot"):
        rows += quot_rows(quot_qs().filter(id__in=project_ids).select_related("work_category"), status)
    if kind in ("",) + MINOR_KINDS:
        from projects.minor import workflow_queryset as minor_qs

        mq = minor_qs().filter(id__in=project_ids).select_related("work_category")
        if kind:
            mq = mq.filter(procurement_type__code=kind)
        rows += minor_rows(mq, status)
    rows.sort(key=lambda r: (r["p"].ward_id or 0, r["kind"], r["p"].name))
    return rows


def by_sector(rows):
    """क्षेत्रअनुसार (क्षेत्र नराखिएका अन्त्यमा)."""
    groups = {}
    for r in rows:
        s = r["p"].sector
        groups.setdefault(s.id if s else None, (s, []))[1].append(r)
    out = [{"sector": s, "name": s.name if s else "क्षेत्र नराखिएको", **totals(rs)}
           for _k, (s, rs) in sorted(groups.items(), key=lambda kv: (kv[1][0] is None, kv[1][0].sort if kv[1][0] else 0, kv[0] or 0))]
    return out


def by_kind(rows):
    return [{"kind": k, "label": lbl, **totals([r for r in rows if r["kind"] == k])}
            for k, lbl in KINDS.items() if any(r["kind"] == k for r in rows)]
