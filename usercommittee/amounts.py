"""रकम जाँच — लागत अनुमान र अन्तिम मूल्याङ्कन/भुक्तानी (सर्भरमा; फारमका JS ले पनि यही नियम देखाउँछन्)।

लागत अनुमान:
  * कुनै रकम ऋणात्मक हुन नहुने; कन्टिन्जेन्सी बजेटभन्दा बढी हुन नहुने
  * बजेट योजनाको विनियोजित रकमभन्दा बढी हुन नहुने
  * उपभोक्ता अंशदान (श्रमदान) कुल लागतको पालिकाले तोकेको न्यूनतम % भन्दा कम हुन नहुने (० = जाँच नगर्ने)
अन्तिम मूल्याङ्कन:
  * कार्यालय + उपभोक्ता = जम्मा मूल्याङ्कन (रु. १ सम्म फरक चल्छ)
  * कार्यालयले तिर्ने रकम लागत अनुमानको कार्यालय अंश (बजेट − कन्टिन्जेन्सी) भन्दा बढी हुन नहुने
  * खुद भुक्तानी (कार्यालय − कर − किस्ता) ऋणात्मक हुन नहुने
  * मूल्याङ्कन कुल लागत अनुमानभन्दा बढी भए चेतावनी मात्र
"""
from decimal import Decimal

from django.db import connection

TOLERANCE = Decimal("1")
ZERO = Decimal("0")


def rs(v):
    return f"रु. {Decimal(v or 0):,.2f}"


def min_user_pct():
    v = getattr(getattr(connection, "tenant", None), "min_user_contribution_pct", 0) or 0
    return Decimal(str(v))


def pct_str(v):
    return f"{Decimal(v).normalize():f}"


def user_pct(user_contribution, total_cost):
    total_cost = Decimal(total_cost or 0)
    if total_cost <= 0:
        return ZERO
    return (Decimal(user_contribution or 0) * 100 / total_cost).quantize(Decimal("0.01"))


def check_estimate(project, budget, contingency, user_contribution):
    """returns (errors, warnings)"""
    errors, warnings = [], []
    if min(budget, contingency, user_contribution) < 0:
        errors.append("रकम ऋणात्मक हुन मिल्दैन।")
        return errors, warnings
    if budget <= 0:
        errors.append("विनियोजित (बजेट) रकम ० भन्दा बढी हुनुपर्छ।")
    if contingency > budget:
        errors.append(f"कन्टिन्जेन्सी {rs(contingency)} बजेट {rs(budget)} भन्दा बढी भयो।")
    allocated = Decimal(project.budget or 0) if project is not None else ZERO
    if allocated > 0 and budget > allocated + TOLERANCE:
        errors.append(f"लागत अनुमानको बजेट {rs(budget)} योजनाको विनियोजित रकम {rs(allocated)} भन्दा बढी भयो। "
                      "पहिले योजनाको विनियोजित रकम संशोधन गर्नुहोस्।")
    total = budget - contingency + user_contribution
    need = min_user_pct()
    pct = user_pct(user_contribution, total)
    if need > 0 and total > 0 and pct < need:
        errors.append(f"उपभोक्ता अंशदान {pct_str(pct)}% मात्र भयो — पालिकाको नियम अनुसार कम्तीमा {pct_str(need)}% चाहिन्छ "
                      f"(कम्तीमा {rs(total * need / 100)})।")
    elif user_contribution == 0:
        warnings.append("उपभोक्ता अंशदान (श्रमदान) ० राखिएको छ।")
    return errors, warnings


def check_final(project, valuation, office, user, total_tax, installments_paid=ZERO):
    """returns (errors, warnings)"""
    errors, warnings = [], []
    if min(valuation, office, user, total_tax) < 0:
        errors.append("रकम ऋणात्मक हुन मिल्दैन।")
        return errors, warnings
    if valuation <= 0:
        errors.append("जम्मा मूल्याङ्कन रकम ० भन्दा बढी हुनुपर्छ।")
    if abs(office + user - valuation) > TOLERANCE:
        errors.append(f"कार्यालयको {rs(office)} र उपभोक्ताको {rs(user)} जोड्दा {rs(office + user)} हुन्छ, "
                      f"जम्मा मूल्याङ्कन {rs(valuation)} सँग मिलेन।")
    est = getattr(project, "cost_estimate", None)
    if est is not None:
        share = Decimal(est.budget or 0) - Decimal(est.contingency_amount or 0)
        if office > share + TOLERANCE:
            errors.append(f"कार्यालयबाट भुक्तानी {rs(office)} लागत अनुमान अनुसारको कार्यालय अंश {rs(share)} भन्दा बढी हुन मिल्दैन।")
        if valuation > Decimal(est.total_cost or 0) + TOLERANCE:
            warnings.append(f"मूल्याङ्कन {rs(valuation)} कुल लागत अनुमान {rs(est.total_cost)} भन्दा "
                            f"{rs(valuation - est.total_cost)} बढी छ — बढी भाग उपभोक्ता समितिले बेहोर्ने।")
    if project is not None:
        from projects.budget import check_payment
        if (e := check_payment(project, office, "अन्तिम भुक्तानी")):
            errors.append(e)
    net = office - total_tax - installments_paid
    if net < 0:
        errors.append(f"खुद भुक्तानी {rs(net)} ऋणात्मक भयो (कार्यालय {rs(office)} − कर {rs(total_tax)} − "
                      f"किस्ता {rs(installments_paid)})। कर वा रकम मिलाउनुहोस्।")
    return errors, warnings


def estimate_summary(est):
    """स्वीकृत modal आदिका लागि."""
    if est is None:
        return None
    need = min_user_pct()
    pct = user_pct(est.user_contribution, est.total_cost)
    return {"pct": pct, "need": need, "ok": not (need > 0 and pct < need),
            "office": Decimal(est.budget or 0) - Decimal(est.contingency_amount or 0),
            "user": est.user_contribution, "total": est.total_cost}
