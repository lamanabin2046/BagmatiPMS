"""वडा: नम्बर (नेपाली अङ्कमा नाम), क्रम, थप्ने र प्रयोग जाँच — पालिकाको सेटिङ पेज र SaaS Manager दुवैले प्रयोग गर्छन्।

वडाको नाम नेपाली अङ्कमा बस्छ ("१", "२" …), किनकि पुराना पत्र/प्रतिवेदनले सोही नाम छाप्छन्।
"""
NP = str.maketrans("0123456789", "०१२३४५६७८९")
EN = str.maketrans("०१२३४५६७८९", "0123456789")
MAX_WARDS = 40


def np_num(n):
    return str(n).translate(NP)


def ward_int(name):
    """'१२' / '12' / 'वडा नं. ३' -> 12 / 12 / 3 ; अङ्क नभए None."""
    digits = "".join(ch for ch in str(name or "").translate(EN) if ch.isdigit())
    return int(digits) if digits else None


def sorted_wards(qs=None):
    from .models import Ward

    items = list(qs if qs is not None else Ward.objects.all())
    return sorted(items, key=lambda w: (ward_int(w.name) is None, ward_int(w.name) or 0, w.name))


def ensure_wards(total):
    """१ देखि total सम्मका नभएका वडा थप्छ (भएकालाई छुँदैन)। थपिएका वडाको सूची फर्काउँछ।
    हालको schema (connection) मा चल्छ — SaaS बाट चलाउँदा schema_context भित्र बोलाउनुहोस्।"""
    from .models import Ward

    total = max(0, min(int(total or 0), MAX_WARDS))
    have = {ward_int(w.name) for w in Ward.objects.all()}
    created = []
    for i in range(1, total + 1):
        if i not in have:
            created.append(Ward.objects.create(name=np_num(i)))
    return created


def ward_usage(ward):
    """वडासँग जोडिएका अभिलेख: {"योजना": n, ...} (शून्य भएका बाहेक)। मेटाउनुअघि जाँच्न।"""
    from projects.models import Project

    from .models import WadaStaff, WardChairperson, WardEngineer, WardSachib

    counts = {
        "योजना": Project.objects.filter(ward=ward).count(),
        "वडा कर्मचारी": WadaStaff.objects.filter(wards=ward).count(),
        "वडा सचिव": WardSachib.objects.filter(ward=ward).count(),
        "वडा इन्जिनियर": WardEngineer.objects.filter(ward=ward).count(),
        "वडा अध्यक्ष (लगइन)": WardChairperson.objects.filter(ward=ward).count(),
    }
    return {k: v for k, v in counts.items() if v}
