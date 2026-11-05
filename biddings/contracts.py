"""बोलपत्र सम्झौता परिवर्तन: म्याद थप (ऐन दफा ५६), भेरिएसन आदेश (दफा ५४) र ढिलाइ हर्जाना.

भेरिएसन (सार्वजनिक खरिद (दोस्रो संशोधन) ऐन, २०८३): कुल परिवर्तनको प्रतिशतअनुसार स्वीकृत गर्ने अधिकारी
    ५% सम्म — राजपत्राङ्कित तृतीय श्रेणीको कार्यालय प्रमुख
    १०% सम्म — द्वितीय श्रेणी · १५% सम्म — प्रथम श्रेणी · १५% भन्दा बढी — विभागीय प्रमुख
  पालिकाको कार्यालय प्रमुखले स्वीकृत गर्न सक्ने सीमा सेटिङमा (variation_office_pct); त्योभन्दा बढीमा माथिल्लो
  निकायको निर्णय र कागजात अनिवार्य। विज्ञ समूहको सिफारिस अभिलेख हुन्छ।
संशोधित सम्झौता रकम = कबोल रकम + स्वीकृत भेरिएसन; मूल्याङ्कन (रनिङ/अन्तिम) यसभन्दा बढी हुन नहुने।

म्याद थप: म्याद सकिनुभन्दा कम्तीमा तोकिएको दिन (पूर्वनिर्धारित २१) अघि निवेदन; “हर्जाना बिना” (दोष नभएको)
  वा “हर्जाना सहित”। पहिलेका (कारण नखुलेका) म्याद थपलाई हर्जाना बिना मानिन्छ।

ढिलाइ हर्जाना: हर्जाना लाग्ने अन्तिम मिति = मूल म्याद वा पछिल्लो “हर्जाना बिना” म्याद थप।
  दिन = काम सम्पन्न मिति − त्यो मिति; रकम = सम्झौता रकम × दैनिक दर × दिन, बढीमा अधिकतम %।
"""
from decimal import Decimal

ZERO = Decimal("0")
TOL = Decimal("1")
TIERS = [(Decimal("5"), "राजपत्राङ्कित तृतीय श्रेणीको कार्यालय प्रमुख"), (Decimal("10"), "राजपत्राङ्कित द्वितीय श्रेणीको कार्यालय प्रमुख"),
         (Decimal("15"), "राजपत्राङ्कित प्रथम श्रेणीको कार्यालय प्रमुख"), (None, "विभागीय प्रमुख")]


def D(v):
    return Decimal(str(v or 0))


def limits():
    from projects.procurement import limits as L

    return L()


def variations(contract):
    return list(contract.variations.all()) if contract is not None else []


def variation_total(contract):
    return sum((D(v.amount) for v in variations(contract)), ZERO)


def revised_amount(bid, contract):
    return D(bid.bidding_amount) + variation_total(contract)


def pct(part, whole):
    whole = D(whole)
    return (D(part) * 100 / whole).quantize(Decimal("0.01")) if whole else ZERO


def authority_for(cum_pct):
    """कुल भेरिएसन % अनुसार ऐनले तोकेको अधिकारी."""
    a = abs(D(cum_pct))
    for cap, who in TIERS:
        if cap is None or a <= cap:
            return who
    return TIERS[-1][1]


def ld_deadline(contract):
    """हर्जाना लाग्ने अन्तिम मिति — मूल म्याद वा पछिल्लो हर्जाना बिनाको म्याद थप."""
    if contract is None:
        return None
    d = contract.contract_expire_date
    for e in contract.extensions.all():
        if e.kind != "penalty" and (d is None or e.extended_expiry_date > d):
            d = e.extended_expiry_date
    return d


def compute_ld(bid, contract, completed_on):
    """(दिन, रकम, अन्तिम मिति, दर, अधिकतम रकम)."""
    L = limits()
    deadline = ld_deadline(contract)
    amount_base = D(bid.bidding_amount)
    cap = (amount_base * D(L.ld_max_pct) / 100).quantize(Decimal("0.01"))
    if not deadline or not completed_on or completed_on <= deadline:
        return 0, ZERO, deadline, D(L.ld_rate_per_day), cap
    days = (completed_on - deadline).days
    amt = (amount_base * D(L.ld_rate_per_day) / 100 * days).quantize(Decimal("0.01"))
    return days, min(amt, cap), deadline, D(L.ld_rate_per_day), cap
