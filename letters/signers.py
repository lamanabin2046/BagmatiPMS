"""पत्रमा हस्ताक्षर गर्ने अधिकारी (प्रत्यायोजन).

प्रमुख प्रशासकीय अधिकृत (वा Admin) ले "स्वीकृत / हस्ताक्षर अधिकारी" पेजबाट पत्रको प्रकारअनुसार अधिकृत तोक्छ।
पत्रको editable_letter key → प्रकार (KEY_KIND); तोकिएको नभए "all", त्यो पनि नभए प्रमुख प्रशासकीय अधिकृत।
टिप्पणी (स्वीकृत गर्ने) र वडाका पत्र यहाँ पर्दैनन्।
"""
from django.db import connection

CAO_POST = "प्रमुख प्रशासकीय अधिकृत"
DELEGATED_NOTE = "प्रमुख प्रशासकीय अधिकृतबाट अख्तियारी प्राप्त"
SIGN_TO = {"1", "3", "4", "8", "10"}   # Admin, योजना अधिकृत, इन्जिनियर, पालिका इन्जिनियर, लेखा अधिकृत

KINDS = [
    ("all", "सबै पत्र", "तल छुट्टै नतोकिएका सबै पत्र"),
    ("bank_letter", "बैंक खाता खोल्ने पत्र", "उपभोक्ता समितिको बैंक खाता खोल्ने सिफारिस"),
    ("work_order", "कार्यादेश", "उपभोक्ता समिति, बोलपत्र, दरभाउपत्र, संस्था / समिति"),
    ("agreement", "सम्झौता (कार्यालयको तर्फबाट)", "उपभोक्ता समिति, बोलपत्र, दरभाउपत्र, संस्था, राजस्व ठेक्का"),
    ("extension", "म्याद थप पत्र", "उपभोक्ता समितिको म्याद थप"),
    ("invite", "आह्वान / सूचना पत्र", "दरभाउपत्र आह्वान, सम्झौता गर्न आउने, संस्था प्रस्ताव आह्वान, राजस्व सूचना"),
    ("other", "अन्य पत्र", "हस्तान्तरण, राजस्व स्वीकृति पत्र र ताकेता पत्र"),
]
KIND_LABEL = {k: lbl for k, lbl, _h in KINDS}

KEY_KIND = {
    "user.print_bank_letter": "bank_letter",
    "user.print_work_order": "work_order", "bidding.print_work_order": "work_order",
    "quatation.print_quatation_work_order": "work_order", "sanstha.work_order": "work_order",
    "user.print_contract_paper": "agreement", "bidding.print_contract_paper": "agreement",
    "quatation.print_quatation_agreement": "agreement", "sanstha.agreement": "agreement", "revenue.agreement": "agreement",
    "user.print_extended_letter": "extension",
    "quatation.send_quatation_letter": "invite", "bidding.print_contract_invite": "invite",
    "sanstha.invite_letter": "invite", "sanstha.public_notice": "invite", "revenue.notice": "invite",
    "user.print_handover": "other", "revenue.acceptance": "other", "revenue.reminder": "other",
}


def _cao():
    tenant = getattr(connection, "tenant", None)
    return {"name": getattr(tenant, "cao_name", "") or "", "post": CAO_POST, "note": "", "delegated": False}


def person_name(user):
    from tenants.context_processors import ROLE_PROFILE

    prof = getattr(user, ROLE_PROFILE.get(str(user.user_type), ""), None) if ROLE_PROFILE.get(str(user.user_type)) else None
    return getattr(prof, "name", "") or user.get_full_name() or user.mobile


def assignments():
    """kind -> LetterSigner (सक्रिय प्रयोगकर्ता मात्र)."""
    from .models import LetterSigner

    return {s.kind: s for s in LetterSigner.objects.select_related("user").filter(user__is_active=True)}


def signer(kind, _cache=None):
    """{name, post, note, delegated} — यो प्रकारको पत्रमा हस्ताक्षर गर्ने."""
    a = assignments() if _cache is None else _cache
    s = a.get(kind) or a.get("all")
    if s is None:
        return _cao()
    from accounts.permissions import ROLE_LABEL

    post = s.post or ROLE_LABEL.get(str(s.user.user_type), "अधिकृत").split(" (")[0]
    return {"name": person_name(s.user), "post": post, "note": DELEGATED_NOTE, "delegated": True}


def kind_for_key(key):
    if key in KEY_KIND:
        return KEY_KIND[key]
    base = key.rsplit(".", 1)[0]          # जस्तै "...tippani.1"
    return KEY_KIND.get(base)
