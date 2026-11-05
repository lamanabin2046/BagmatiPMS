"""भूमिका र अनुमति (role-based access).

हरेक अनुमति एउटा code हो (जस्तै "uc.approve")। कुन भूमिकालाई के अनुमति छ भन्ने:
  1. Admin ले "भूमिका र अनुमति" पेजमा बदलेको भए त्यही (RolePermission)
  2. नत्र तलको DEFAULT_ROLE_PERMS
थप, कुनै व्यक्तिलाई छुट्टै अनुमति दिन सकिन्छ (UserPermission) — जस्तै CAO ले
रुजु/स्वीकृतको अधिकार कुनै अधिकृतलाई प्रत्यायोजन गर्दा।

प्रयोग:  from accounts.permissions import has_perm
         if has_perm(request.user, "uc.approve"): ...
टेम्प्लेटमा: {% if 'uc.approve' in me.perms %}
"""

ROLES = [
    ("1", "प्रशासक (Admin)"),
    ("2", "प्रमुख प्रशासकीय अधिकृत"),
    ("3", "योजना अधिकृत"),
    ("4", "इन्जिनियर"),
    ("5", "वडा कर्मचारी"),
    ("6", "वडा सचिव"),
    ("7", "वडा इन्जिनियर"),
    ("8", "पालिका इन्जिनियर"),
    ("9", "वडा अध्यक्ष"),
    ("10", "लेखा अधिकृत"),
]
ROLE_LABEL = dict(ROLES)

# (code, group, label, help)
PERMISSIONS = [
    ("project.manage", "योजना", "योजना दर्ता / सम्पादन", "नयाँ योजना थप्ने र सच्याउने"),

    ("uc.committee", "उपभोक्ता समिति", "समिति गठन / सम्पादन", "पदाधिकारी, सदस्य र तिनका कागजात राख्ने (वडा तहका कर्मचारीले आफ्नै वडाको मात्र)"),
    ("uc.member_docs", "उपभोक्ता समिति", "सदस्यका कागजात हेर्ने", "नागरिकता, NID र फोटो हेर्ने"),
    ("uc.estimate", "उपभोक्ता समिति", "लागत अनुमान थप्ने", ""),
    ("uc.estimate_edit", "उपभोक्ता समिति", "लागत अनुमान सच्याउने", "स्वीकृत हुनुअघि मात्र"),

    ("uc.sifaris_portal", "वडा सिफारिस", "पोर्टलबाट सिफारिस गर्ने", "वडा सचिवले आफ्नो वडाको"),
    ("uc.sifaris_upload", "वडा सिफारिस", "कागजी सिफारिस अपलोड गर्ने", "वडाबाट कागजमा आएको सिफारिस स्क्यान गरी राख्ने"),

    ("uc.approve", "रुजु / स्वीकृत", "रुजु / स्वीकृत गर्ने (सबै योजना)", "पालिका केन्द्रित र वडा प्रत्यायोजित दुवै"),
    ("uc.approve_ward", "रुजु / स्वीकृत", "आफ्नो वडाको योजना स्वीकृत गर्ने", "वडा प्रत्यायोजित तरिकाका, आफ्नै वडाका योजना मात्र"),
    ("uc.delegate", "रुजु / स्वीकृत", "स्वीकृत अधिकार प्रत्यायोजन गर्ने", "अरू अधिकृतलाई रुजु / स्वीकृतको अधिकार दिने/हटाउने"),

    ("uc.public_audit", "सम्झौता र भुक्तानी", "सार्वजनिक परीक्षण / अनुगमन विवरण राख्ने", "मुचुल्का, उपस्थिति, फोटो र अनुगमन समितिको प्रतिवेदन"),
    ("uc.agreement_print", "सम्झौता र भुक्तानी", "सम्झौता, टिप्पणी, बैंक पत्र, कार्यादेश छाप्ने", ""),
    ("uc.valuation", "सम्झौता र भुक्तानी", "अन्तिम मूल्याङ्कन गर्ने", "उपभोक्ता समितिको मूल्याङ्कन / किस्ता र बोलपत्र / दरभाउपत्रको अन्तिम बिल"),
    ("uc.payment_print", "सम्झौता र भुक्तानी", "अन्तिम टिप्पणी / हस्तान्तरण छाप्ने", ""),

    ("uc.progress_photo", "काम प्रगति", "प्रगति फोटो अपलोड", ""),
    ("field.app", "काम प्रगति", "साइट (मोबाइल) — फोटो खिच्ने", "मोबाइलबाट योजनास्थलको फोटो, GPS, भौतिक प्रगति % र टिप्पणी राख्ने (इन्जिनियर / साइट इन्जिनियर)"),
    ("field.view", "काम प्रगति", "साइट फोटो — हेर्ने मात्र", "योजनाअनुसार साइट फोटो, GPS स्थान र प्रगति हेर्ने (फोटो राख्न नमिल्ने)"),
    ("mb.view", "काम प्रगति", "नापी किताब हेर्ने", "BOQ, नापी र भौतिक प्रगति"),
    ("mb.boq", "काम प्रगति", "परिमाण सूची (BOQ) राख्ने", "हातैले वा Excel बाट"),
    ("mb.measure", "काम प्रगति", "नापी दर्ता गर्ने", "साइटको नापजाँच (संख्या × लम्बाइ × चौडाइ × उचाइ)"),
    ("uc.inspection", "काम प्रगति", "निरीक्षण टिप्पणी", ""),

    ("bid.view", "बोलपत्र ठेक्का", "ठेक्का कार्यप्रवाह हेर्ने", "बोलपत्र, सम्झौता, जमानत र भुक्तानीको स्थिति"),
    ("bid.manage", "बोलपत्र ठेक्का", "ठेक्का विवरण भर्ने", "आह्वान, मूल्याङ्कन, PG माग, सम्झौता, पेश्की, रनिङ र अन्तिम बिल"),
    ("bid.approve", "बोलपत्र ठेक्का", "बोलपत्र रुजु / स्वीकृत गर्ने", "मूल्याङ्कन र आशयको सूचनापछि"),
    ("bid.print", "बोलपत्र ठेक्का", "ठेक्काका कागजात छाप्ने", "आशयको सूचना, टिप्पणी, सम्झौता, कार्यादेश, भुक्तानी टिप्पणी"),

    ("quot.view", "दरभाउपत्र खरिद", "दरभाउपत्र कार्यप्रवाह हेर्ने", "आह्वान, तुलना, सम्झौता र भुक्तानीको स्थिति"),
    ("quot.manage", "दरभाउपत्र खरिद", "दरभाउपत्र विवरण भर्ने", "सूचीकृत फर्म, आह्वान, प्राप्त दर, सम्झौता र अन्तिम बिल"),
    ("quot.approve", "दरभाउपत्र खरिद", "दरभाउपत्र रुजु / स्वीकृत गर्ने", "न्यूनतम दर स्वीकृत"),
    ("quot.print", "दरभाउपत्र खरिद", "दरभाउपत्रका कागजात छाप्ने", "आह्वान पत्र, टिप्पणी, सम्झौता, कार्यादेश, भुक्तानी टिप्पणी"),

    ("retention.recommend", "धरौटी फिर्ता", "धरौटी फिर्ता सिफारिस अपलोड गर्ने", "इन्जिनियर वा वडाको सिफारिस पत्र (स्क्यान) राख्ने"),
    ("retention.manage", "धरौटी फिर्ता", "धरौटी फिर्ता टिप्पणी र फिर्ता दर्ता", "सिफारिसपछि टिप्पणी छाप्ने, फिर्ता भएको दर्ता गर्ने"),

    ("app.view", "वार्षिक खरिद योजना", "खरिद योजना हेर्ने", "योजनाअनुसार खरिद विधि, अनुमानित लागत र समयतालिका"),
    ("app.manage", "वार्षिक खरिद योजना", "खरिद विधि छान्ने / खरिद योजना बनाउने", "कानुनी सीमा र आधार जाँचेर विधि तोक्ने"),
    ("app.approve", "वार्षिक खरिद योजना", "खरिद योजना स्वीकृत गर्ने", "निर्णय नं. सहित स्वीकृत"),
    ("minor.view", "सोझै खरिद / अमानत / संस्था", "कार्यप्रवाह हेर्ने", "सोझै खरिद, अमानत र संस्था/समिति मार्फतका खरिद"),
    ("minor.manage", "सोझै खरिद / अमानत / संस्था", "विवरण भर्ने", "लागत अनुमान, दरभाउ/प्रस्ताव, आदेश, हाजिरी, जाँचपास, भुक्तानी"),
    ("minor.approve", "सोझै खरिद / अमानत / संस्था", "छनौट / अमानत स्वीकृत गर्ने", ""),
    ("minor.print", "सोझै खरिद / अमानत / संस्था", "टिप्पणी, आदेश र भुक्तानी टिप्पणी छाप्ने", ""),
    ("firm.view", "फर्म दर्ता", "फर्म / निर्माण व्यवसायी हेर्ने", "दर्ता, कामको इतिहास र कार्यसम्पादन"),
    ("firm.manage", "फर्म दर्ता", "फर्म दर्ता / सम्पादन", "PAN, वर्ग, सम्पर्क, सूचीकृत"),
    ("firm.blacklist", "फर्म दर्ता", "कालोसूचीमा राख्ने / हटाउने", "निर्णय वा PPMO सूचनाअनुसार"),
    ("rev.view", "राजस्व आम्दानी", "राजस्व ठेक्का हेर्ने", "स्रोत, बोलपत्र, सम्झौता, असुली र अनुगमन"),
    ("rev.manage", "राजस्व आम्दानी", "राजस्व स्रोत र ठेक्का विवरण भर्ने", "स्रोत दर्ता, मूल्याङ्कन, आह्वान, बोलपत्र, सम्झौता, फरफारक"),
    ("rev.survey", "राजस्व आम्दानी", "प्राविधिक सर्वेक्षण र अनुगमन", "परिमाण, वातावरणीय स्वीकृति, नक्सा/फोटो, निरीक्षण"),
    ("rev.approve", "राजस्व आम्दानी", "राजस्व ठेक्का स्वीकृत गर्ने", "प्रशासनिक स्वीकृति र सफल बोलपत्रदाता स्वीकृति"),
    ("rev.collect", "राजस्व आम्दानी", "किस्ता असुली दर्ता", "रसिदसहित भुक्तानी प्राप्ति"),
    ("rev.print", "राजस्व आम्दानी", "राजस्व ठेक्काका कागजात छाप्ने", "टिप्पणी, सूचना, स्वीकृति पत्र, सम्झौता, फरफारक"),
    ("budget.view", "बजेट नियन्त्रण", "बजेट स्थिति हेर्ने", "शीर्षक/योजनाअनुसार विनियोजित, प्रतिबद्धता, खर्च र बाँकी"),
    ("budget.manage", "बजेट नियन्त्रण", "बजेट शीर्षक र रकमान्तर", "बजेट शीर्षक थप्ने/बदल्ने; योजनाको बजेट थप, कटौती, रकमान्तर दर्ता गर्ने"),

    ("letters.edit", "पत्र", "पत्र सम्पादन (एउटा पत्र मात्र)", "छाप्नुअघि त्यही योजनाको पत्रको पाठ बदल्ने"),
    ("letters.templates", "पत्र", "पत्रको ढाँचा (सबै योजनामा)", "पालिकाको ढाँचा — placeholder सहित, सबै पत्रमा लागू"),
    ("dashboard.view", "प्रतिवेदन", "मुख्य ड्यासबोर्ड", "बजेट, खर्च, विधि/चरण, वडा, राजस्व र ध्यान दिनुपर्ने काम एकै ठाउँमा"),
    ("backup.manage", "सेटिङ", "ब्याकअप", "डाटा र फाइलको ब्याकअप बनाउने / डाउनलोड गर्ने"),
    ("alerts.manage", "सेटिङ", "SMS / इमेल सूचना", "SMS र इमेल सूचनाको सेटिङ, परीक्षण र पठाइएका सूचनाको लग"),
    ("yearend.close", "सेटिङ", "आर्थिक वर्ष बन्द गर्ने", "क्रमागत योजना सार्ने, आ.व. लक गर्ने"),
    ("report.uc", "प्रतिवेदन", "खरिद तथा भुक्तानी प्रतिवेदन", "उपभोक्ता समिति, बोलपत्र, दरभाउपत्र — विनियोजित, भुक्तानी, कर कट्टी (एकीकृत वा छुट्टै)"),
    ("report.outputs", "प्रतिवेदन", "भौतिक उपलब्धि प्रतिवेदन", "कति कि.मि. बाटो, कति भवन … (सबै वडा, आ.व. अनुसार)"),
    ("settings.staff", "सेटिङ", "कर्मचारी व्यवस्थापन", ""),
    ("settings.tax", "सेटिङ", "कर शीर्षक", "अन्तिम भुक्तानीमा कट्टी हुने करका शीर्षक थप्ने/बदल्ने"),
    ("settings.office", "सेटिङ", "कार्यालय सेटिङ र पत्र शीर्ष", "लोगो, नारा, वेबसाइट, इमेल र पत्र शीर्ष मिलाउने"),
    ("settings.procurement", "सेटिङ", "खरिद विधिका रकम सीमा", "सोझै खरिद, दरभाउपत्र, उपभोक्ता समिति आदिको सीमा (कानुन संशोधन हुँदा)"),
    ("settings.sectors", "सेटिङ", "क्षेत्र / उपक्षेत्र", "योजनाको क्षेत्र र उपक्षेत्र थप्ने/बदल्ने"),
    ("settings.outputs", "सेटिङ", "कामको प्रकार र उपलब्धि सूचक", "सडक, भवन … र तिनका सूचक (कि.मि., वटा) थप्ने/बदल्ने"),
    ("settings.roles", "सेटिङ", "भूमिका र अनुमति मिलाउने", "Admin को यो अनुमति हटाउन मिल्दैन"),
]
PERM_LABEL = {c: l for c, _g, l, _h in PERMISSIONS}
PERM_CODES = set(PERM_LABEL)

# Admin बाट कहिल्यै नहट्ने (आफैँलाई बाहिर थुन्न नमिल्ने)
LOCKED = {("1", "settings.roles")}

ALL = {c for c, *_ in PERMISSIONS}
DEFAULT_ROLE_PERMS = {
    "1": ALL - {"uc.approve_ward"},
    "2": {"field.view", "dashboard.view", "yearend.close", "rev.view", "rev.approve", "rev.print", "uc.approve", "uc.delegate", "uc.member_docs", "uc.agreement_print", "uc.payment_print", "letters.edit",
          "report.outputs", "report.uc", "bid.view", "bid.approve", "bid.print",
          "quot.view", "quot.approve", "quot.print", "retention.manage", "budget.view", "app.view", "app.approve", "minor.view", "minor.approve", "minor.print", "mb.view", "firm.view", "firm.blacklist"},
    "3": {"field.view", "dashboard.view", "rev.view", "rev.manage", "rev.collect", "rev.print", "uc.public_audit", "project.manage", "uc.committee", "uc.member_docs", "uc.estimate", "uc.sifaris_upload",
          "uc.agreement_print", "uc.valuation", "uc.payment_print", "letters.edit", "report.outputs", "report.uc", "settings.outputs", "settings.sectors",
          "bid.view", "bid.manage", "bid.print", "quot.view", "quot.manage", "quot.print",
          "retention.recommend", "retention.manage", "budget.view", "budget.manage", "app.view", "app.manage", "minor.view", "minor.manage", "minor.print", "mb.view", "mb.boq", "firm.view", "firm.manage"},
    # इन्जिनियर (४, ७, ८): लागत अनुमान, अन्तिम मूल्याङ्कन र भौतिक प्रगति मात्र भर्ने — बाँकी हेर्ने मात्र (ENGINEER_MAX)
    "4": {"field.app", "field.view", "uc.estimate", "uc.valuation", "mb.view", "mb.boq", "mb.measure",
          "rev.view", "bid.view", "quot.view", "app.view", "minor.view", "firm.view"},
    "5": {"field.view", "uc.sifaris_upload"},
    "6": {"field.view", "uc.public_audit", "uc.committee", "uc.member_docs", "uc.sifaris_portal", "uc.sifaris_upload", "letters.edit", "retention.recommend"},
    "7": {"field.app", "field.view", "uc.estimate", "uc.valuation", "uc.progress_photo", "mb.view", "mb.boq", "mb.measure",
          "bid.view", "quot.view", "app.view", "minor.view"},
    "8": {"field.app", "field.view", "dashboard.view", "uc.estimate", "uc.estimate_edit", "uc.valuation", "uc.inspection",
          "mb.view", "mb.boq", "mb.measure", "report.outputs", "report.uc",
          "rev.view", "bid.view", "quot.view", "budget.view", "app.view", "minor.view", "firm.view"},
    "9": {"field.view", "uc.approve_ward", "uc.member_docs"},
    # लेखा अधिकृत: भुक्तानी टिप्पणी, कर कट्टी, धरौटी फिर्ता, बजेट र राजस्व असुली
    "10": {"field.view", "dashboard.view", "uc.agreement_print", "uc.payment_print", "report.uc", "report.outputs",
           "bid.view", "bid.print", "quot.view", "quot.print", "minor.view", "minor.print", "retention.manage",
           "budget.view", "app.view", "rev.view", "rev.collect", "rev.print", "firm.view", "mb.view", "settings.tax"},
}

# इन्जिनियरले भर्न मिल्ने: लागत अनुमान, अन्तिम मूल्याङ्कन, भौतिक प्रगति; अरू सबै हेर्ने मात्र।
# "भूमिका र अनुमति" पेजबाट यसबाहिरको अनुमति इन्जिनियर भूमिकालाई दिन मिल्दैन (CAO को व्यक्तिगत प्रत्यायोजन भने लागू हुन्छ)।
ENGINEER_ROLES = {"4", "7", "8"}
ENGINEER_FILL = {"uc.estimate", "uc.estimate_edit", "mb.boq",                      # लागत अनुमान
                 "uc.valuation",                                                   # अन्तिम मूल्याङ्कन
                 "field.app", "uc.progress_photo", "mb.measure", "uc.inspection"}  # भौतिक प्रगति
ENGINEER_MAX = ENGINEER_FILL | {c for c, *_ in PERMISSIONS if c.endswith(".view")} | {"report.uc", "report.outputs"}


def engineer_locked(role, code):
    return str(role) in ENGINEER_ROLES and code not in ENGINEER_MAX


# व्यक्तिगत रूपमा दिन मिल्ने अनुमति (प्रत्यायोजन) र कसलाई दिन मिल्ने
# CAO ले प्रत्यायोजन गर्न मिल्ने स्वीकृत अधिकार र कसलाई (योजना अधिकृत, इन्जिनियर, पालिका इन्जिनियर, Admin)
DELEGATE_TO = {"1", "3", "4", "8"}
DELEGABLE = [
    ("uc.approve", "उपभोक्ता समिति", "सम्झौता रुजु / स्वीकृत"),
    ("bid.approve", "बोलपत्र ठेक्का", "मूल्याङ्कनपछि स्वीकृत"),
    ("quot.approve", "दरभाउपत्र", "न्यूनतम दर स्वीकृत"),
    ("minor.approve", "सोझै / अमानत / संस्था", "छनौट / अमानत स्वीकृत"),
    ("app.approve", "खरिद योजना", "वार्षिक खरिद योजना स्वीकृत"),
]
GRANTABLE = {code: DELEGATE_TO for code, *_ in DELEGABLE}


def role_perms(role):
    """एउटा भूमिकाका प्रभावी अनुमति (Admin ले बदलेको + default)."""
    from .models import RolePermission

    perms = set(DEFAULT_ROLE_PERMS.get(str(role), set()))
    for perm, allowed in RolePermission.objects.filter(role=str(role)).values_list("perm", "allowed"):
        if (str(role), perm) in LOCKED:
            continue
        (perms.add if allowed else perms.discard)(perm)
    perms |= {p for r, p in LOCKED if r == str(role)}
    if str(role) in ENGINEER_ROLES:      # इन्जिनियर: भर्ने काम ३ वटा मात्र, बाँकी हेर्ने
        perms &= ENGINEER_MAX
    return perms & PERM_CODES


def user_perms(user):
    """प्रयोगकर्ताका सबै अनुमति (भूमिका + व्यक्तिगत), एउटा request भित्र cache।"""
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    cached = getattr(user, "_pms_perms", None)
    if cached is not None:
        return cached
    from .models import UserPermission

    perms = role_perms(user.user_type)
    perms |= set(UserPermission.objects.filter(user=user).values_list("perm", flat=True))
    user._pms_perms = frozenset(perms)
    return user._pms_perms


def has_perm(user, code):
    return code in user_perms(user)


def clear_cache(user):
    if hasattr(user, "_pms_perms"):
        del user._pms_perms
