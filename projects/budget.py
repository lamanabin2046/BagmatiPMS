"""बजेट नियन्त्रण — बजेट शीर्षक, योजनाको विनियोजित रकम, प्रतिबद्धता र खर्च.

तह:
  बजेट शीर्षक (BudgetHead.allocated)  ≥  त्यस शीर्षकका योजनाको विनियोजित रकमको जोड
  योजनाको विनियोजित (Project.budget)  ≥  खर्च (कुल भुक्तानी — कर/धरौटी कट्टी समेत)

प्रतिबद्धता (committed):
  उपभोक्ता समिति — लागत अनुमानको कार्यालयले बेहोर्ने बजेट (कन्टिन्जेन्सी समेत)
  बोलपत्र / दरभाउपत्र — सम्झौता / स्वीकृत कबोल रकम
खर्च (spent): खरिद तथा भुक्तानी प्रतिवेदनको "कुल भुक्तानी" (gross) — usercommittee.reports।

नियम:
  * योजनाको विनियोजित रकम शीर्षकमा बाँकी रकमभन्दा बढी राख्न नमिल्ने
  * विनियोजित रकम खर्चभन्दा कम गर्न नमिल्ने; प्रतिबद्धताभन्दा कम गर्न नमिल्ने
  * कुनै पनि भुक्तानीपछि कुल खर्च विनियोजित रकमभन्दा बढी हुन नमिल्ने (थप/रकमान्तर गर्नुपर्छ)
  * कबोल / सम्झौता रकम विनियोजितभन्दा बढी भए चेतावनी (बहुवर्षीय हुन सक्ने)
"""
from decimal import Decimal

from django.db.models import Sum

TOL = Decimal("1")
ZERO = Decimal("0")


def D(v):
    return Decimal(str(v or 0))


def rs(v):
    from .templatetags.outputs import money

    return f"रु. {money(D(v))}"


def _committed(row):
    if row["kind"] == "uc":
        return (row["office_share"] + row["contingency"]) if row.get("office_share") is not None else ZERO
    return row["contract"] or ZERO


def usage(project_ids):
    """{project_id: {"spent", "committed", "row"}} — प्रतिवेदनकै हिसाब।"""
    from usercommittee.reports import all_rows

    out = {}
    for r in all_rows(list(project_ids)):
        u = out.setdefault(r["p"].id, {"spent": ZERO, "committed": ZERO, "row": r})
        u["spent"] += r["gross"]
        u["committed"] = max(u["committed"], _committed(r))
    return out


def project_usage(project):
    return usage([project.id]).get(project.id, {"spent": ZERO, "committed": ZERO, "row": None})


def spent(project):
    return project_usage(project)["spent"]


def distributed(head, exclude_ids=()):
    """शीर्षकमा राखिएका योजनाको विनियोजित रकमको जोड."""
    from .models import Project

    qs = Project.objects.filter(budget_head=head).exclude(id__in=[i for i in exclude_ids if i])
    return D(qs.aggregate(s=Sum("budget"))["s"])


def head_room(head, exclude_ids=()):
    return D(head.allocated) - distributed(head, exclude_ids)


def closed_fy_error(project=None, fiscalyear_id=None):
    """बन्द भएको आ.व. मा भुक्तानी / बजेट परिवर्तन रोक्ने (projects/yearend.py)."""
    from .models import FiscalYear

    fy = getattr(project, "fiscalyear", None) if project is not None and getattr(project, "fiscalyear_id", None) else None
    if fy is None and fiscalyear_id:
        fy = FiscalYear.objects.filter(id=fiscalyear_id).first()
    if fy is not None and fy.closed_at:
        return f"आ.व. {fy.name} बन्द भइसकेको छ — यस आ.व. का योजनामा भुक्तानी वा बजेट परिवर्तन गर्न मिल्दैन।"
    return None


def check_project_budget(project, new_budget, head, fiscalyear_id=None):
    """योजना थप्दा / सच्याउँदा: (errors). project नयाँ भए pk None."""
    if (e := closed_fy_error(project if getattr(project, "pk", None) else None, fiscalyear_id)):
        return [e]
    errors = []
    new_budget = D(new_budget)
    if new_budget < 0:
        return ["विनियोजित रकम ऋणात्मक हुन मिल्दैन।"]
    if head is not None:
        fy = fiscalyear_id or getattr(project, "fiscalyear_id", None)
        if fy and head.fiscalyear_id != int(fy):
            errors.append(f"बजेट शीर्षक “{head}” अर्कै आर्थिक वर्षको हो।")
        room = head_room(head, [getattr(project, "pk", None)])
        if new_budget > room + TOL:
            errors.append(f"बजेट शीर्षक “{head}” मा बाँकी {rs(room)} मात्र छ — विनियोजित {rs(new_budget)} "
                          f"राख्न मिल्दैन ({rs(new_budget - room)} अपुग)।")
    if getattr(project, "pk", None):
        u = project_usage(project)
        old = D(project.budget)
        if new_budget < u["spent"] - TOL:
            errors.append(f"यस योजनामा {rs(u['spent'])} खर्च भइसकेको छ — विनियोजित रकम त्योभन्दा कम गर्न मिल्दैन।")
        elif u["committed"] and new_budget < u["committed"] - TOL and old >= u["committed"] - TOL:
            errors.append(f"यस योजनाको प्रतिबद्धता (लागत अनुमान / सम्झौता) {rs(u['committed'])} छ — "
                          "विनियोजित रकम त्योभन्दा कम गर्न मिल्दैन।")
    return errors


def check_payment(project, total_after, what="भुक्तानी"):
    """भुक्तानीपछिको कुल खर्च (gross) विनियोजितभित्र छ? त्रुटि सन्देश वा None."""
    if (e := closed_fy_error(project)):
        return e
    budget = D(project.budget)
    total_after = D(total_after)
    if budget <= 0:          # पुराना अभिलेख (विनियोजित नभरिएको) — रोक्दैन
        return None
    if total_after > budget + TOL:
        return (f"{what}पछि कुल खर्च {rs(total_after)} विनियोजित {rs(budget)} भन्दा बढी हुन्छ "
                f"({rs(total_after - budget)} अपुग)। पहिले बजेट थप / रकमान्तर गर्नुहोस्।")
    return None


def over_budget_warning(project, amount, label):
    budget = D(project.budget)
    if budget > 0 and D(amount) > budget + TOL:
        return f"{label} {rs(amount)} विनियोजित {rs(budget)} भन्दा बढी छ — बजेट थप / रकमान्तर चाहिन्छ।"
    return None


def budget_note(project):
    """कार्यप्रवाह / फारमका लागि छोटो टिप्पणी."""
    u = project_usage(project)
    budget = D(project.budget)
    return f"विनियोजित {rs(budget)} · खर्च {rs(u['spent'])} · बाँकी {rs(budget - u['spent'])}"
