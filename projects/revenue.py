"""राजस्व आम्दानी — राजस्व स्रोतको ठेक्का: स्रोत दर्तादेखि फरफारकसम्म (बोलपत्र / दरभाउपत्र जस्तै चरण).

चरण:
    स्रोत दर्ता → प्राविधिक सर्वेक्षण → राजस्व मूल्याङ्कन → प्रशासनिक स्वीकृति → बोलपत्र आह्वान
    → बोलपत्र खोल्ने र मूल्याङ्कन → सफल बोलपत्रदाता स्वीकृति → सम्झौता → राजस्व असुली (किस्ता) → फरफारक
    + अनुगमन (निरीक्षण, उत्खनन परिमाण, उल्लङ्घन र जरिवाना) — सम्झौतापछि जुनसुकै बेला

नियम (सर्भरमा जाँचिन्छ):
  * नदीजन्य पदार्थ: सर्वेक्षण अनिवार्य; IEE/EIA (वा BES) स्वीकृति र म्याद बाँकी; अनुमानित परिमाण सर्वेक्षणभन्दा बढी हुन नहुने
  * अनुमानित राजस्व = परिमाण × दर (आफैँ हिसाब); न्यूनतम कबोल अङ्क अनुमानित राजस्वभन्दा कम राख्दा कारण चाहिने
  * प्रशासनिक स्वीकृति नभई आह्वान नहुने; स्वीकृतपछि मूल्याङ्कन लक; स्वीकृत गर्ने अधिकारीले फिर्ता पठाउन सक्ने
  * आह्वान कम्तीमा १५ दिन; अन्तिम मितिअघि बोलपत्र खोल्न नमिल्ने; म्यादपछि आएको बोलपत्र नलिइने
  * न्यूनतम कबोलभन्दा कम, जमानत नपुगेको वा अयोग्य बोलपत्र छनौट नहुने; कालोसूची (पालिका / PPMO) रोक्ने
  * सबैभन्दा बढी कबोल गर्ने योग्य बोलपत्रदाता सिफारिस हुन्छ, तर स्वचालित रूपमा ठेक्का दिइँदैन — स्वीकृत गर्ने अधिकारीले
    छान्छ; अर्को छान्दा कारण अनिवार्य
  * सम्झौता: कार्यसम्पादन जमानत अनिवार्य; किस्ता तालिका आफैँ बन्छ; सम्झौतापछि रकम बदल्न नमिल्ने
  * फरफारक: सबै किस्ता र जरिवाना असुल भएपछि मात्र; जमानत फिर्ता त्यसपछि मात्र
"""
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from usercommittee.workflow import _link, _modal, add_next, bs_date

ZERO = Decimal("0")
NOTICE_DAYS = 15
LABEL = "राजस्व आम्दानी"
NEEDS_SURVEY = {"riverbed"}
UNITS = {"riverbed": "घन मिटर", "parking": "वर्ष", "haat": "वर्ष", "toilet": "वर्ष", "advert": "वर्ष", "ferry": "वर्ष", "other": ""}

STEP_INFO = {
    "source": ("स्रोत", "स्रोत दर्ता"),
    "survey": ("सर्वेक्षण", "प्राविधिक सर्वेक्षण"),
    "estimate": ("मूल्याङ्कन", "राजस्व मूल्याङ्कन"),
    "approval": ("स्वीकृति", "प्रशासनिक स्वीकृति"),
    "notice": ("आह्वान", "बोलपत्र आह्वान सूचना"),
    "bids": ("बोलपत्र", "बोलपत्र खोल्ने र मूल्याङ्कन"),
    "award": ("स्वीकृत", "सफल बोलपत्रदाता स्वीकृति"),
    "agreement": ("सम्झौता", "सम्झौता र जमानत"),
    "collection": ("असुली", "राजस्व असुली (किस्ता)"),
    "settlement": ("फरफारक", "सम्झौता सम्पन्न र फरफारक"),
}
STEPS = list(STEP_INFO)
COLUMNS = [(k, STEP_INFO[k][0], STEP_INFO[k][1]) for k in STEPS]


def D(v):
    return Decimal(str(v or 0))


def money(v):
    return f"{D(v):,.0f}"


def np(v):
    return str(v).translate(str.maketrans("0123456789", "०१२३४५६७८९"))


def needs_survey(s):
    return s.category in NEEDS_SURVEY


def security_required(s, amount):
    return (D(amount) * D(s.bid_security_pct) / 100).quantize(Decimal("1"))


def responsive(s, b):
    """छनौट योग्य: कागजात / योग्यता पुगेको, जमानत ठीक (रकम भरेको भए तोकिएको % पुगेको), न्यूनतम कबोलभन्दा कम नभएको,
    र पहिले स्वीकृत भई सम्झौता नगरेको होइन."""
    if b.defaulted or not (b.eligible and b.security_ok):
        return False
    if b.security_amount is not None and D(b.security_amount) < security_required(s, b.amount):
        return False
    return s.min_bid is None or D(b.amount) >= D(s.min_bid)


def current_bids(s):
    return [b for b in s.bids.all() if b.round == s.tender_round]


def ranked(s):
    bids = sorted(current_bids(s), key=lambda b: (not responsive(s, b), -D(b.amount), b.id))
    return [(b, responsive(s, b)) for b in bids]


def recommended(s):
    r = ranked(s)
    return r[0][0] if r and r[0][1] else None


def prints_of(s):
    out = {}
    for p in s.prints.all():
        out.setdefault(p.doc_type, p)
    return out


def settings_():
    from .procurement import limits

    return limits()


def months_late(due, on):
    days = (on - due).days
    return 0 if days <= 0 else -(-days // 30)


def late_fee(amount, due, on, pct=None):
    """विलम्ब शुल्क = रकम × % × ढिलो महिना (३० दिनको एक महिना, अधुरो महिना पूरा गनिने)."""
    pct = D(settings_().rev_late_fee_pct if pct is None else pct)
    if not pct or not amount:
        return ZERO
    return (D(amount) * pct / 100 * months_late(due, on)).quantize(Decimal("1"))


def money_status(s):
    L = settings_()
    inst = list(s.instalments.all())
    due = sum((D(i.amount) for i in inst), ZERO)
    paid = sum((D(i.paid_amount) for i in inst), ZERO)
    today = date.today()
    overdue = [i for i in inst if i.due_date < today and D(i.paid_amount) < D(i.amount)]
    soon = [i for i in inst if today <= i.due_date <= today + timedelta(days=L.rev_reminder_days) and D(i.paid_amount) < D(i.amount)]
    late_pending = sum((late_fee(D(i.amount) - D(i.paid_amount), i.due_date, today, L.rev_late_fee_pct) for i in overdue), ZERO)
    insp = list(s.inspections.all())
    penalty = sum((D(x.penalty) for x in insp), ZERO)
    payments = [p for i in inst for p in i.payments.all()]
    ext = list(s.extractions.all())
    extracted = sum((D(x.quantity) for x in ext), ZERO)
    limit = D(s.est_quantity) if needs_survey(s) else ZERO
    return {"instalments": inst, "due": due, "paid": paid, "outstanding": due - paid, "overdue": overdue, "soon": soon,
            "overdue_amount": sum((D(i.amount) - D(i.paid_amount) for i in overdue), ZERO), "penalty": penalty,
            "late_pending": late_pending, "late_paid": sum((D(i.late_fee_paid) for i in inst), ZERO),
            "inspections": insp, "payments": payments, "extractions": ext, "extracted": extracted, "qty_limit": limit,
            "extracted_pct": round(extracted * 100 / limit) if limit else None}


def sign_overdue(s):
    """स्वीकृत भएको तोकिएको दिनभित्र सम्झौता नगरेको."""
    if not s.award_at or s.agreement_date:
        return False
    return (date.today() - s.award_at.date()).days > settings_().rev_sign_days


def env_expiring(s):
    """सम्झौता अवधिभित्रै वातावरणीय स्वीकृति सकिने / सकिन लागेको."""
    if not needs_survey(s) or not s.env_valid_until or s.settled_on or s.cancelled_on:
        return ""
    if s.env_valid_until < date.today():
        return f"वातावरणीय स्वीकृतिको म्याद {bs_date(s.env_valid_until)} मा सकियो — उत्खनन रोक्नुपर्छ।"
    if s.end_date and s.env_valid_until < s.end_date:
        return f"वातावरणीय स्वीकृति {bs_date(s.env_valid_until)} मा सकिन्छ (ठेक्का {bs_date(s.end_date)} सम्म) — नवीकरण गराउनुहोस्।"
    if s.env_valid_until <= date.today() + timedelta(days=30):
        return f"वातावरणीय स्वीकृतिको म्याद {bs_date(s.env_valid_until)} मा सकिँदैछ।"
    return ""


def history(s):
    """अघिल्ला वर्ष / पुनः आह्वानका रेकर्ड (पुरानो पहिले)."""
    out, cur, seen = [], s.previous, set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        out.append(cur)
        cur = cur.previous
    return list(reversed(out))


def env_problem(s):
    """नदीजन्य पदार्थको वातावरणीय स्वीकृति जाँच — समस्या भए सन्देश."""
    if not needs_survey(s):
        return ""
    if s.env_type not in ("bes", "iee", "eia") or not s.env_ref or not s.env_approved_on:
        return "नदीजन्य पदार्थको IEE / EIA (वा BES) स्वीकृति विवरण चाहिन्छ।"
    if s.env_valid_until and s.env_valid_until < date.today():
        return f"वातावरणीय स्वीकृतिको म्याद {bs_date(s.env_valid_until)} मा सकिएको छ।"
    return ""


def survey_done(s):
    return bool(s.survey_date and s.survey_quantity) if needs_survey(s) else True


def workflow(s, user=None):
    from accounts.permissions import user_perms

    P = user_perms(user) if user is not None else set()
    manage, survey, approver, collect, printing = ("rev.manage" in P, "rev.survey" in P, "rev.approve" in P,
                                                   "rev.collect" in P, "rev.print" in P)
    prints = prints_of(s)
    bids = current_bids(s)
    rec = recommended(s)
    ms = money_status(s)
    sid = s.id
    st = {}

    st["source"] = {"done": True, "date": s.created_at.date() if s.created_at else None,
                    "note": f"{s.get_category_display()}" + (f" · वडा नं. {np(s.ward.name)}" if s.ward else "") +
                            (f" · {s.location}" if s.location else ""),
                    "actions": [_link("स्रोत विवरण सम्पादन", "revenue_edit", sid)] if manage and not s.approved_at else []}

    # सर्वेक्षण
    actions = []
    if (survey or manage) and not s.approved_at:
        actions.append(_link("सर्वेक्षण सम्पादन" if s.survey_date else "सर्वेक्षण विवरण भर्नुहोस्", "revenue_survey", sid,
                             primary=not s.survey_date))
    if needs_survey(s):
        note = (f"उपलब्ध {money(s.survey_quantity)} {s.unit}" if s.survey_quantity else "")
        if s.env_type:
            note += f" · {s.env_type.upper()}" + (f" म्याद {bs_date(s.env_valid_until)}" if s.env_valid_until else "")
        if (e := env_problem(s)) and s.survey_date:
            note += f" · ⚠ {e}"
    else:
        note = "यस प्रकारमा ऐच्छिक" + (f" · {bs_date(s.survey_date)}" if s.survey_date else "")
    st["survey"] = {"done": survey_done(s), "date": s.survey_date, "note": note, "actions": actions}

    # मूल्याङ्कन
    actions = []
    if manage and not s.approved_at and survey_done(s):
        actions.append(_link("मूल्याङ्कन सम्पादन" if s.est_revenue else "राजस्व मूल्याङ्कन गर्नुहोस्", "revenue_estimate", sid,
                             primary=not s.est_revenue))
    note = ""
    if s.est_revenue:
        note = f"{money(s.est_quantity)} {s.unit} × रु. {money(s.rate)} = रु. {money(s.est_revenue)} · न्यूनतम कबोल रु. {money(s.min_bid)}"
    if s.returned_remarks and not s.approved_at:
        note += f" · फिर्ता: {s.returned_remarks}"
    st["estimate"] = {"done": bool(s.est_revenue and s.min_bid), "date": s.estimate_date, "note": note, "actions": actions}

    # प्रशासनिक स्वीकृति
    actions = []
    if s.est_revenue and printing:
        actions.append(_link(("✓ " if "estimate" in prints else "") + "मूल्याङ्कन टिप्पणी", "revenue_print", sid, "estimate",
                             new_tab=True, primary="estimate" not in prints and not s.approved_at))
    if s.est_revenue and not s.approved_at and approver:
        actions.append(_modal("स्वीकृत / फिर्ता गर्नुहोस्", "revenue_approve", sid, icon="stamp"))
    elif s.approved_at and P:
        actions.append(_modal("स्वीकृति विवरण", "revenue_approve", sid, primary=False))
    note = (f"{s.approver_name}" + (f" · निर्णय {s.approval_ref}" if s.approval_ref else "")) if s.approved_at else \
        ("प्रमुख प्रशासकीय अधिकृत वा अधिकार पाएका" if s.est_revenue else "")
    st["approval"] = {"done": bool(s.approved_at), "date": s.approved_at.date() if s.approved_at else None, "note": note,
                      "remarks": s.approval_remarks, "actions": actions}

    # आह्वान
    actions = []
    if s.approved_at and manage and not bids:
        actions.append(_link("आह्वान सम्पादन" if s.notice_date else "बोलपत्र आह्वान गर्नुहोस्", "revenue_notice", sid,
                             primary=not s.notice_date))
    if s.notice_date and printing:
        actions.append(_link(("✓ " if "notice" in prints else "") + "आह्वान सूचना", "revenue_print", sid, "notice",
                             new_tab=True, primary="notice" not in prints))
    note = f"पेश गर्ने अन्तिम मिति {bs_date(s.bid_deadline)} · जमानत {np(f'{D(s.bid_security_pct):g}')}%" if s.notice_date else ""
    if s.tender_round > 1:
        note = f"{np(s.tender_round)} औँ पटक आह्वान · " + note
    online_n = sum(1 for o in s.online_bids.all() if o.round == s.tender_round)
    if online_n:
        note += f" · {np(online_n)} अनलाइन बोलपत्र (सिलबन्दी)"
    st["notice"] = {"done": bool(s.notice_date), "date": s.notice_date, "note": note, "actions": actions}

    # बोलपत्र
    actions = []
    if s.notice_date and manage and not s.award_at:
        actions.append(_link("बोलपत्र सम्पादन" if bids else "प्राप्त बोलपत्र भर्नुहोस्", "revenue_bids", sid, primary=not bids))
    note = ""
    if bids:
        note = f"{np(len(bids))} बोलपत्र · योग्य {np(sum(1 for _b, ok in ranked(s) if ok))}"
        if rec:
            note += f" · उच्चतम योग्य {rec.name} रु. {money(rec.amount)}"
    if bids and printing:
        actions.append(_link(("✓ " if "comparison" in prints else "") + "तुलनात्मक विवरण", "revenue_print", sid, "comparison",
                             new_tab=True, primary="comparison" not in prints))
    no_valid = bool(s.notice_date and not s.award_at and ((bids and rec is None) or
                                                            (not bids and s.bid_deadline and s.bid_deadline < date.today())))
    if no_valid and manage:
        actions.append(_link("पुनः बोलपत्र आह्वान", "revenue_retender", sid, primary=True))
    if no_valid:
        note += " · मान्य बोलपत्र छैन — पुनः आह्वान गर्नुहोस्"
    st["bids"] = {"done": bool(bids and s.opening_date), "date": s.opening_date, "note": note, "actions": actions}

    # सफल बोलपत्रदाता
    actions = []
    if bids and not s.award_at and approver:
        actions.append(_modal("सफल बोलपत्रदाता स्वीकृत गर्नुहोस्", "revenue_award", sid, icon="stamp"))
    elif s.award_at and P:
        actions.append(_modal("स्वीकृति विवरण", "revenue_award", sid, primary=False))
    if s.award_at and printing:
        actions.append(_link(("✓ " if "acceptance" in prints else "") + "स्वीकृति पत्र", "revenue_print", sid, "acceptance",
                             new_tab=True, primary="acceptance" not in prints))
    note = f"{s.selected.name} · रु. {money(s.selected.amount)}" if s.award_at and s.selected else ""
    if sign_overdue(s):
        note += f" · {np(settings_().rev_sign_days)} दिनभित्र सम्झौता गर्न आएन"
        if approver or manage:
            actions.append(_link("सम्झौता नगरेको — जमानत जफत", "revenue_default", sid, primary=True))
    st["award"] = {"done": bool(s.award_at), "date": s.award_at.date() if s.award_at else None, "note": note,
                   "remarks": s.award_remarks, "actions": actions}

    # सम्झौता
    actions = []
    if s.award_at and manage and not ms["paid"]:
        actions.append(_link("सम्झौता सम्पादन" if s.agreement_date else "सम्झौता विवरण भर्नुहोस्", "revenue_agreement", sid,
                             primary=not s.agreement_date))
    if s.agreement_date and printing:
        actions.append(_link(("✓ " if "agreement" in prints else "") + "सम्झौता पत्र", "revenue_print", sid, "agreement",
                             new_tab=True, primary="agreement" not in prints))
    held = [b for b in s.bids.all() if b.security_status == "held" and b.security_kind]
    if s.agreement_date and held and manage:
        actions.append(_link(f"बोलपत्र जमानत फिर्ता ({np(len(held))})", "revenue_securities", sid, query="status=held"))
    if s.agreement_date and approver and not s.settled_on and not s.cancelled_on:
        actions.append(_link("सम्झौता रद्द", "revenue_cancel", sid))
    note = (f"रु. {money(s.contract_amount)} · {bs_date(s.start_date)} – {bs_date(s.end_date)} · जमानत रु. {money(s.security_amount)}"
            if s.agreement_date else "")
    st["agreement"] = {"done": bool(s.agreement_date), "date": s.agreement_date, "note": note, "actions": actions}

    # असुली
    inst = ms["instalments"]
    actions = []
    if inst and (collect or manage) and not s.settled_on and not s.cancelled_on:
        actions.append(_link("किस्ता असुली दर्ता", "revenue_collect", sid, primary=ms["outstanding"] > 0))
    if printing and not s.settled_on and not s.cancelled_on:
        for i in ms["overdue"][:3]:
            actions.append(_link(f"ताकेता पत्र (किस्ता {np(i.n)})", "revenue_print", sid, "reminder", new_tab=True,
                                 query=f"i={i.id}"))
    note = ""
    if inst:
        note = f"असुल रु. {money(ms['paid'])} / {money(ms['due'])}"
        if ms["overdue"]:
            note += f" · {np(len(ms['overdue']))} किस्ता म्याद नाघेको (रु. {money(ms['overdue_amount'])})"
        if ms["late_pending"]:
            note += f" · विलम्ब शुल्क रु. {money(ms['late_pending'])}"
        if ms["soon"]:
            note += f" · {np(len(ms['soon']))} किस्ता {np(settings_().rev_reminder_days)} दिनभित्र बुझाउनुपर्ने"
    if s.cancelled_on:
        note = f"सम्झौता रद्द ({bs_date(s.cancelled_on)}) · असुल रु. {money(ms['paid'])}"
    st["collection"] = {"done": bool(inst and (ms["outstanding"] <= 0 or s.cancelled_on)),
                        "date": max((p.date for p in ms["payments"]), default=None), "note": note, "actions": actions}

    # फरफारक
    actions = []
    if s.agreement_date and manage and not s.settled_on:
        actions.append(_link("फरफारक गर्नुहोस्", "revenue_settle", sid, primary=ms["outstanding"] <= 0 or bool(s.cancelled_on)))
    if (s.settled_on or s.cancelled_on) and manage and not any(True for _f in s.followers.all()):
        if s.cancelled_on and s.end_date and s.end_date > date.today():
            actions.append(_link("बाँकी अवधिको पुनः बोलपत्र", "revenue_next", sid, query="mode=remainder", primary=True))
        else:
            actions.append(_link("अर्को आ.व. का लागि सार्नुहोस्", "revenue_next", sid))
    if s.settled_on and printing:
        actions.append(_link(("✓ " if "settlement" in prints else "") + "फरफारक टिप्पणी", "revenue_print", sid, "settlement",
                             new_tab=True, primary="settlement" not in prints))
    note = ("जमानत फिर्ता भएको" if s.security_released else ("जमानत जफत" if s.security_forfeited else "जमानत फिर्ता बाँकी")) \
        if s.settled_on else (f"सम्झौता अवधि {bs_date(s.end_date)} सम्म" if s.end_date else "")
    if s.settled_on and D(s.arrears):
        note += f" · बक्यौता रु. {money(s.arrears)}"
    st["settlement"] = {"done": bool(s.settled_on), "date": s.settled_on, "note": note, "actions": actions}

    today = date.today()
    overdue = bool(ms["overdue"]) and not s.settled_on
    expired = bool(s.end_date and s.end_date < today and not s.settled_on)
    deadline_passed = bool(s.bid_deadline and s.bid_deadline < today and not bids)
    alerts = [x for x in (env_expiring(s),) if x]
    if ms["extracted_pct"] is not None and ms["extracted_pct"] >= 80 and not s.settled_on:
        alerts.append(f"स्वीकृत परिमाणको {np(ms['extracted_pct'])}% उत्खनन भइसक्यो।")
    if sign_overdue(s):
        alerts.append("स्वीकृत बोलपत्रदाताले म्यादभित्र सम्झौता गरेन — बोलपत्र जमानत जफत गरी अर्को मान्य बोलपत्रदाता छान्नुहोस्।")
    steps, current = [], None
    for n, key in enumerate(STEPS, start=1):
        info = st[key]
        if info["done"]:
            state = "done"
        elif current is None:
            current = n
            state = "warning" if (key == "collection" and overdue) or (key == "bids" and deadline_passed) or \
                (key == "settlement" and expired) else "current"
        else:
            state = "pending"
        short, label = STEP_INFO[key]
        steps.append({"n": n, "key": key, "short": short, "label": label, "state": state,
                      "date_bs": bs_date(info.get("date")), **info})
    cur = next((x for x in steps if x["n"] == current), None)
    return steps, {
        "s": s, "current": current, "current_key": cur["key"] if cur else "", "current_label": cur["label"] if cur else "",
        "done_count": sum(1 for x in steps if x["state"] == "done"), "total": len(steps), "completed": current is None,
        "overdue": overdue, "expired": expired, "deadline_passed": deadline_passed, "money": ms,
        "ranked": ranked(s), "recommended": rec,
        "contractor": s.selected.name if s.selected else (rec.name if rec else ""),
        "amount": s.contract_amount or (s.selected.amount if s.selected else None),
        "monitor": {"show": bool(s.agreement_date), "can_add": (survey or manage) and bool(s.agreement_date) and not s.settled_on
                    and not s.cancelled_on, "url": reverse("revenue_inspect", args=[sid]),
                    "extract_url": reverse("revenue_extract", args=[sid]), "track": needs_survey(s)},
        "alerts": alerts, "history": history(s), "retenders": list(s.retenders.all()),
        "sign_overdue": sign_overdue(s), "cancelled": bool(s.cancelled_on),
    }


def row_cells(steps):
    by = {x["key"]: x for x in steps}
    return [by.get(k) for k, _s, _l in COLUMNS]


def with_next(steps, return_to, summary=None):
    if not return_to:
        return
    if summary:
        summary["monitor"]["url"] = add_next(summary["monitor"]["url"], return_to)
        summary["monitor"]["extract_url"] = add_next(summary["monitor"]["extract_url"], return_to)
    for x in steps:
        for a in x.get("actions", []):
            if not a["new_tab"] and not a.get("modal"):
                a["url"] = add_next(a["url"], return_to)


def queryset():
    from .models import RevenueSource

    return (RevenueSource.objects.select_related("ward", "fiscalyear", "selected", "previous")
            .prefetch_related("bids", "instalments__payments", "inspections", "prints", "docs", "extractions", "retenders",
                              "online_bids", "followers"))


def schedule(start, end, amount, n):
    """किस्ता तालिका: पहिलो किस्ता सम्झौताको सुरुमै, बाँकी अवधिभरि बराबर अन्तरमा; रकम बराबर (अन्तिममा मिलान)."""
    n = max(1, int(n))
    span = max((end - start).days, 1)
    each = (D(amount) / n).quantize(Decimal("1"))
    out = []
    for i in range(n):
        due = start + timedelta(days=round(span * i / n))
        amt = each if i < n - 1 else D(amount) - each * (n - 1)
        out.append((i + 1, due, amt))
    return out


PRINT_NEEDS = {
    "estimate": (lambda s: s.est_revenue, "पहिले राजस्व मूल्याङ्कन गर्नुहोस्।"),
    "notice": (lambda s: s.notice_date, "पहिले बोलपत्र आह्वान विवरण भर्नुहोस्।"),
    "comparison": (lambda s: s.bids.exists(), "पहिले प्राप्त बोलपत्र भर्नुहोस्।"),
    "acceptance": (lambda s: s.award_at, "पहिले सफल बोलपत्रदाता स्वीकृत गर्नुहोस्।"),
    "agreement": (lambda s: s.agreement_date, "पहिले सम्झौता विवरण भर्नुहोस्।"),
    "receipt": (lambda s: True, ""),
    "reminder": (lambda s: True, ""),
    "settlement": (lambda s: s.settled_on, "पहिले फरफारक गर्नुहोस्।"),
}
