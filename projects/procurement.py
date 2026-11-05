"""खरिद विधि छनौट — सार्वजनिक खरिद ऐन, २०६३ (दोस्रो संशोधन, २०८३ समेत) र नियमावली, २०६४ अनुसार.

रकम सीमा पालिकाको सेटिङमा (ProcurementLimits) — कानुन संशोधन हुँदा त्यहीँबाट मिलाइन्छ।

विधि र मुख्य शर्त:
  उपभोक्ता समिति (ऐन दफा ४४) — निर्माण कार्य, लागत अनुमान तोकिएको सीमाभित्र, र तलका कम्तीमा एउटा आधार
  संस्था / समिति (दफा ४६)     — अन्य सेवा (सचेतना, तालिम, सशक्तीकरण …); सीमाभन्दा बढीमा खुला आशयपत्र
  अमानत (दफा ४५)             — नियमित मर्मत/सरसफाइ, सेवा सञ्चालनसँग जोडिएको, जरुरी, जोखिमपूर्ण … (रकम सीमा छैन)
  बोलपत्र (दफा १३–१४)         — जुनसुकै रकम; दरभाउपत्र सीमाभन्दा बढीमा अनिवार्य (राष्ट्रिय: कम्तीमा २१ दिनको सूचना)
  सिलबन्दी दरभाउपत्र (दफा ४०) — दरभाउपत्र सीमासम्म (कम्तीमा ७ दिनको सूचना)
  सोझै खरिद (दफा ४१)          — सोझै खरिद सीमासम्म (परामर्श सेवाको छुट्टै सीमा); खरिद टुक्र्याउन नपाइने (दफा ८)
"""
from collections import OrderedDict
from decimal import Decimal

ZERO = Decimal("0")

METHODS = OrderedDict([
    ("uc", {"label": "उपभोक्ता समिति मार्फत", "icon": "fa-users", "law": "दफा ४४"}),
    ("sanstha", {"label": "संस्था / समिति मार्फत", "icon": "fa-building", "law": "दफा ४६"}),
    ("amanat", {"label": "अमानत मार्फत", "icon": "fa-hand-holding-dollar", "law": "दफा ४५"}),
    ("bid", {"label": "बोलपत्र मार्फत", "icon": "fa-file-signature", "law": "दफा १३–१४"}),
    ("quot", {"label": "सिलबन्दी दरभाउपत्र मार्फत", "icon": "fa-envelope-open-text", "law": "दफा ४०"}),
    ("direct", {"label": "सोझै खरिद मार्फत", "icon": "fa-file-invoice-dollar", "law": "दफा ४१"}),
])
# कार्यप्रवाह भएका विधि (अरूको कार्यप्रवाह पछि थपिने)
WORKFLOW_URL = {"uc": "usercommittee_workflow", "bid": "bid_workflow", "quot": "quot_workflow", "sanstha": "sanstha_workflow"}

GROUNDS = {
    "uc": [  # ऐन दफा ४४ (दोस्रो संशोधन, २०८३)
        ("no_complex", "जटिल प्राविधिक क्षमता आवश्यक नपर्ने"),
        ("economy", "मितव्ययिता, गुणस्तर वा दिगोपनामा अभिवृद्धि हुने"),
        ("local", "स्थानीय स्रोत, साधन, सामग्री र सीप प्रयोग हुने"),
        ("employment", "स्थानीय रोजगारी सिर्जना र लाभग्राहीको सहभागिता हुने"),
        ("maintain", "समिति / समूहले पछि मर्मत सम्भार र सञ्चालन गर्न सक्ने"),
    ],
    "amanat": [  # ऐन दफा ४५ (दोस्रो संशोधन, २०८३)
        ("routine", "नियमित मर्मत सम्भार, सामान्य वा सरसफाइ सम्बन्धी काम (लागत अनुमान गर्न कठिन)"),
        ("service", "चालु सेवा सञ्चालनसँग जोडिएको, त्यसमा परिचित जनशक्तिबाट गर्नुपर्ने काम"),
        ("urgent", "ढिलाइ हुँदा हानि नोक्सानी हुने जरुरी काम"),
        ("risky", "जोखिमपूर्ण वा सुरक्षा संवेदनशील काम"),
    ],
    "sanstha": [  # ऐन दफा ४६
        ("awareness", "सचेतना, अभिमुखीकरण, तालिम वा सशक्तीकरण सम्बन्धी काम"),
        ("effective", "संस्था / समितिबाट गराउँदा छिटो, प्रभावकारी र मितव्ययी हुने"),
    ],
}
NATURE_METHODS = {
    "works": ("uc", "amanat", "bid", "quot", "direct"),
    "goods": ("bid", "quot", "direct"),
    "consulting": ("bid", "direct"),
    "services": ("sanstha", "amanat", "bid", "quot", "direct"),
}
NATURE_LABEL = {"works": "निर्माण कार्य", "goods": "मालसामान", "consulting": "परामर्श सेवा", "services": "अन्य सेवा"}


def rs(v):
    from .templatetags.outputs import money

    return f"रु. {money(Decimal(v or 0), 0)}"


def evaluate(nature, cost, L):
    """हरेक विधि: {"code", "label", "icon", "law", "allowed", "reason", "notes", "grounds", "recommended"}."""
    cost = Decimal(str(cost or 0))
    direct_cap = L.consult_direct_limit if nature == "consulting" else L.direct_limit
    out = []
    for code, meta in METHODS.items():
        ok, why, notes = True, "", []
        if code not in NATURE_METHODS.get(nature, ()):
            ok, why = False, f"{NATURE_LABEL.get(nature, nature)} का लागि यो विधि प्रयोग हुँदैन।"
        elif cost <= 0:
            ok, why = False, "अनुमानित लागत भर्नुहोस्।"
        elif code == "uc":
            if cost > L.uc_limit:
                ok, why = False, f"उपभोक्ता समितिबाट {rs(L.uc_limit)} सम्मको निर्माण कार्य मात्र गराउन मिल्छ।"
            notes.append("दफा ४४ का आधारमध्ये कम्तीमा एउटा पूरा हुनुपर्छ; समितिले काम अरूलाई ठेक्कामा दिन पाउँदैन।")
        elif code == "sanstha":
            if cost > L.sanstha_notice_limit:
                notes.append(f"{rs(L.sanstha_notice_limit)} भन्दा बढी भएकाले खुला आशयपत्र (EOI) माग गर्नुपर्छ।")
            else:
                notes.append("कम्तीमा १५ दिनको सूचना प्रकाशन गरी छनौट गर्नुपर्छ।")
        elif code == "amanat":
            notes.append("रकम सीमा छैन, तर दफा ४५ का आधारमध्ये एउटा हुनुपर्छ।")
        elif code == "bid":
            notes.append("राष्ट्रिय बोलपत्र: कम्तीमा २१ दिनको सूचना (e-GP मा पत्रिका आवश्यक छैन)।")
            if nature == "consulting":
                notes.append("परामर्श सेवामा प्रस्ताव (RFP) मार्फत छनौट।")
        elif code == "quot":
            if cost > L.quot_limit:
                ok, why = False, f"सिलबन्दी दरभाउपत्र {rs(L.quot_limit)} सम्म मात्र — यसभन्दा बढीमा बोलपत्र अनिवार्य।"
            notes.append("कम्तीमा ७ दिनको सूचना; लागत अनुमानभित्रको न्यूनतम मूल्याङ्कित दरभाउपत्र स्वीकृत।")
        elif code == "direct":
            if cost > direct_cap:
                ok, why = False, f"सोझै खरिद {rs(direct_cap)} सम्म मात्र।"
            notes.append("खरिद टुक्र्याउन पाइँदैन (दफा ८); सूचीकृत आपूर्तिकर्ताबाट कम्तीमा ३ दरभाउ लिनुपर्छ।")
        out.append({"code": code, **meta, "allowed": ok, "reason": why, "notes": notes,
                    "grounds": GROUNDS.get(code, []), "recommended": False})
    rec = recommended(nature, cost, L)
    for m in out:
        m["recommended"] = m["code"] == rec and m["allowed"]
    return out


def recommended(nature, cost, L):
    cost = Decimal(str(cost or 0))
    if cost <= 0:
        return ""
    direct_cap = L.consult_direct_limit if nature == "consulting" else L.direct_limit
    if cost <= direct_cap:
        return "direct"
    if nature != "consulting" and cost <= L.quot_limit:
        return "quot"
    return "bid"


def check(nature, method, cost, grounds, L):
    """सुरक्षित गर्नुअघि: त्रुटि सूची."""
    errors = []
    if nature not in NATURE_LABEL:
        errors.append("खरिदको प्रकृति छान्नुहोस्।")
        return errors
    m = next((x for x in evaluate(nature, cost, L) if x["code"] == method), None)
    if m is None:
        errors.append("खरिद विधि छान्नुहोस्।")
    elif not m["allowed"]:
        errors.append(m["reason"])
    elif m["grounds"]:
        valid = {k for k, _ in m["grounds"]}
        if not set(grounds) & valid:
            errors.append(f"{m['label']} का लागि कानुनी आधारमध्ये कम्तीमा एउटा छान्नुहोस् ({m['law']})।")
    return errors


def limits():
    """पालिकाको सीमा (छोटो cache — सूचीमा सयौँ योजनाका लागि बारम्बार query नहोस्)."""
    from django.core.cache import cache
    from django.db import connection

    from .models import ProcurementLimits

    key = f"plimits:{getattr(connection, 'schema_name', 'public')}"
    obj = cache.get(key)
    if obj is None:
        obj = ProcurementLimits.get()
        cache.set(key, obj, 30)
    return obj


CONTINGENCY_FIELD = {"uc": "contingency_uc", "bid": "contingency_bid", "quot": "contingency_quot"}


def contingency_pct(kind):
    """कन्टिन्जेन्सी कट्टी दर % (सेटिङ → खरिद विधिका रकम सीमा) — kind: uc / bid / quot."""
    from decimal import Decimal

    field = CONTINGENCY_FIELD.get(kind)
    v = getattr(limits(), field, None) if field else None
    return Decimal("3") if v is None else Decimal(str(v))


def contingency_amount(kind, amount):
    """रकमको कन्टिन्जेन्सी (२ दशमलव)."""
    from decimal import ROUND_HALF_UP, Decimal

    return (Decimal(str(amount or 0)) * contingency_pct(kind) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)


def forget_limits():
    from django.core.cache import cache
    from django.db import connection

    cache.delete(f"plimits:{getattr(connection, 'schema_name', 'public')}")


def type_for(code):
    from .models import Procurement_Type

    return Procurement_Type.objects.filter(code=code).order_by("id").first()


def code_of(project):
    pt = getattr(project, "procurement_type", None)
    return getattr(pt, "code", "") if pt else ""


def started(project):
    """कार्यप्रवाह सुरु भइसकेको भए (विधि बदल्न नमिल्ने) — कारण, नभए ''."""
    code = code_of(project)
    if code == "uc" and getattr(project, "user_committee", None) is not None:
        return "उपभोक्ता समिति गठन भइसकेको"
    if code == "bid" and project.biddings.exists():
        return "बोलपत्र प्रक्रिया सुरु भइसकेको"
    if code == "quot":
        from quatation.models import Quation
        if Quation.objects.filter(project=project).exists():
            return "दरभाउपत्र प्रक्रिया सुरु भइसकेको"
    return ""


def plan_gate(project):
    """खरिद प्रक्रिया सुरु गर्न मिल्छ? मिल्दैन भने कारण, मिल्छ भने ''.

    पालिकाको सेटिङ (require_approved_plan) खुला भए: स्वीकृत खरिद योजना चाहिन्छ।
    पहिले नै सुरु भइसकेका (पुराना) योजनालाई रोकिँदैन।
    """
    if not limits().require_approved_plan:
        return ""
    plan = getattr(project, "procurement_plan", None)
    if plan is not None and plan.status == "approved":
        return ""
    if started(project) or getattr(project, "minor", None) is not None:
        return ""
    return ("खरिद योजना तयार छ तर स्वीकृत भएको छैन — स्वीकृत भएपछि मात्र खरिद प्रक्रिया सुरु गर्न मिल्छ।" if plan is not None
            else "वार्षिक खरिद योजनामा यो योजनाको खरिद योजना बनेको छैन — पहिले खरिद योजना बनाई स्वीकृत गराउनुहोस्।")


def gate_action(project):
    """कार्यप्रवाहमा देखाउने बटन (खरिद योजनामा जाने)."""
    from django.urls import reverse

    plan = getattr(project, "procurement_plan", None)
    label = "खरिद योजना स्वीकृत गर्नुहोस्" if plan is not None else "खरिद योजना बनाउनुहोस्"
    return {"label": label, "url": reverse("app_plan", args=[project.id]), "primary": True, "new_tab": False}
