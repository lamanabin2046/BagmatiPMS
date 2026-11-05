"""साइडबार र हेडरका खण्ड — एकै ठाउँमा (योजना चक्रको क्रममा).

हेडरमा खण्डका ट्याब (मुख्य › १ कार्यक्रम र बजेट › २ … › ५ सेटिङ), बायाँ साइडबारमा अहिलेको खण्डका पेज मात्र.
हरेक पेज: (शीर्षक, url name, icon, अनुमति, भूमिका, सक्रिय url names, query, उप-समूह).
अहिलेको पेज कुन खण्डमा पर्छ भन्ने: पहिले मेनुका सक्रिय नामबाट, नभए URL को अगाडिको भागबाट.
"""
from django.urls import NoReverseMatch, reverse

UC_ACTIVE = ("usercommittee_workflow view_projects view_usercommittee view_usercommittee_payments add_usercommittee "
             "add_usercommittee_for_project add_cost_estimate add_cost_estimate_for_project view_estimated_projects "
             "add_final_valuation edit_final_valuation view_final_valuation edit_usercommittee extend_usercommittee_date").split()
BID_ACTIVE = ("bid_workflow add_bid_detail view_bid_detail view_approved_projects view_agreement_projects add_advance_payment "
              "add_running_evaluation add_final_payment view_advance_payment view_running_evaluations view_final_payment").split()
QUOT_ACTIVE = ("quot_workflow add_suchikrit_list view_suchikrit_list invite_quatation view_quatation_projects "
               "view_quatation_all_projects add_quatation_amount add_quatation_agreement add_quatation_final_payment "
               "add_quatation_final_payment_sidebar view_quatation_final_payment_sidebar").split()
REV_PERMS = ("rev.view", "rev.manage", "rev.approve", "rev.survey", "rev.collect")


def I(label, url, icon, perms=None, roles=None, active=(), query="", group="", prefix="", match=None, not_roles=None):  # noqa: E741
    return {"label": label, "url_name": url, "icon": icon, "perms": perms, "roles": roles, "active": set(active) | {url},
            "query": query, "group": group, "prefix": prefix, "match": match or {}, "not_roles": not_roles}


SECTIONS = [
    {"key": "main", "num": "", "label": "मुख्य", "items": [
        I("मेरो काम", "my_work", "list-checks"),
        I("मेरो ड्यासबोर्ड", "__home__", "layout-dashboard"),
        I("मुख्य ड्यासबोर्ड", "dashboard", "gauge", perms=("dashboard.view",), active=("yearend", "yearend_report")),
    ]},
    {"key": "budget", "num": "१", "label": "कार्यक्रम र बजेट", "items": [
        I("योजना अभिलेखिकरण", "add_project", "folder-plus", roles=("1",)),
        I("वडाका योजनाहरू", "ward_project_list", "clipboard-list", roles=("6",)),
        I("वडाका योजनाहरू", "ward_engineer_project_list", "clipboard-list", roles=("7",)),
        I("सबै योजनाहरू", "palika_engineer_project_list", "clipboard-list", roles=("8",)),
        I("योजनाको विवरण", "view_projects_engineer", "clipboard", roles=("4",)),
        I("उपभोक्ता समितको विवरण", "view_usercommittee_engineer", "list", roles=("4",)),
        I("वार्षिक खरिद योजना", "app_list", "refresh-cw", perms=("app.view", "app.manage", "app.approve"), active=("app_plan",)),
        I("बजेट स्थिति", "budget_status", "gauge", perms=("budget.view", "budget.manage"), group="बजेट नियन्त्रण"),
        I("थप / कटौती / रकमान्तर", "budget_amendments", "arrow-left-right", perms=("budget.view", "budget.manage"),
          active=("budget_amendment_new",), group="बजेट नियन्त्रण"),
        I("बजेट शीर्षक", "budget_heads", "list-tree", perms=("budget.manage",), group="बजेट नियन्त्रण"),
    ]},
    {"key": "procure", "num": "२", "label": "खरिद र कार्यान्वयन", "items": [
        I("उपभोक्ता समिति", "usercommittee_workflow", "users", active=UC_ACTIVE),
        I("दरभाउपत्र खरिद", "quot_workflow", "clipboard-list", perms=("quot.view",), active=QUOT_ACTIVE, prefix="quot_wf_"),
        I("बोलपत्र ठेक्का", "bid_workflow", "file-text", perms=("bid.view",), active=BID_ACTIVE, prefix="bid_wf_"),
        I("सोझै खरिद", "minor_list", "receipt", perms=("minor.view", "minor.manage", "minor.approve"), query="method=direct",
          match={"method": "direct"}, group="सोझै / अमानत / संस्था", active=("minor_detail",)),
        I("अमानत", "minor_list", "hard-hat", perms=("minor.view", "minor.manage", "minor.approve"), query="method=amanat",
          match={"method": "amanat"}, group="सोझै / अमानत / संस्था"),
        I("संस्था / समिति", "sanstha_workflow", "building", perms=("minor.view", "minor.manage", "minor.approve"),
          group="सोझै / अमानत / संस्था"),
        I("फर्म / निर्माण व्यवसायी", "firm_list", "hard-hat", perms=("firm.view", "firm.manage", "firm.blacklist"),
          active=("firm_detail", "ppmo_list"), group="सम्बन्धित"),
        I("Performance Bank Guarantee", "performance_guarantees", "shield-check", perms=("bid.view",),
          active=("extend_performance_bond",), group="बैंक ग्यारेन्टी"),
        I("Advance Payment Guarantee", "advance_guarantees", "wallet", perms=("bid.view", "quot.view"), group="बैंक ग्यारेन्टी"),
        I("साइट फोटो", "field_home", "smartphone", perms=("field.app", "field.view"), active=("field_project",), group="सम्बन्धित"),
        I("सिफारिस तयार गर्नुहोस", "view_projects_for_recommendation", "file-signature", roles=("6",), group="वडा"),
        I("काम सम्पन्न सिफारिस", "view_projects_for_completion_recommendation", "flag", roles=("6",), group="वडा"),
        I("स्वीकृत गर्ने अधिकारी", "uc_approvers", "shield-check", perms=("uc.delegate",), not_roles=("1",), group="सम्बन्धित"),
    ]},
    {"key": "revenue", "num": "३", "label": "आम्दानी", "items": [
        I("राजस्व आम्दानी", "revenue_list", "landmark", perms=REV_PERMS),
        I("राजस्व प्रतिवेदन", "revenue_report", "chart-column", perms=REV_PERMS),
        I("बोलपत्र जमानत", "revenue_securities_list", "shield-half", perms=REV_PERMS, active=("revenue_securities",)),
        I("SuTRA मिलान", "revenue_sutra", "git-compare", perms=("rev.collect", "rev.manage")),
    ]},
    {"key": "reports", "num": "४", "label": "प्रतिवेदन", "items": [
        I("एकीकृत प्रतिवेदन (सबै)", "uc_report_summary", "layout-dashboard", perms=("report.uc",), match={"kind": ""}),
        I("उपभोक्ता समिति", "uc_report_summary", "users", perms=("report.uc",), query="kind=uc", match={"kind": "uc"}),
        I("बोलपत्र ठेक्का", "uc_report_summary", "file-text", perms=("report.uc",), query="kind=bid", match={"kind": "bid"}),
        I("दरभाउपत्र खरिद", "uc_report_summary", "clipboard-list", perms=("report.uc",), query="kind=quot", match={"kind": "quot"}),
        I("योजनागत वित्तीय विवरण", "uc_report_projects", "table", perms=("report.uc",)),
        I("कर कट्टी प्रतिवेदन", "uc_report_taxes", "receipt", perms=("report.uc",)),
        I("कर तथा धरौटी कट्टी विवरण", "deduction_register", "list-checks", perms=("report.uc",)),
        I("धरौटी फिर्ता", "retention_list", "hand-coins", perms=("report.uc", "retention.recommend", "retention.manage"),
          active=("retention_recommend", "retention_release")),
        I("भौतिक उपलब्धि", "outputs_report", "ruler", perms=("report.outputs",)),
        I("लेखापरीक्षण प्याकेट", "audit_pack", "folder-archive", perms=("report.uc",)),
        I("सबै योजनाहरू (सबै वडा)", "palika_engineer_project_list", "clipboard-list", roles=("1",), group="पालिका स्तरीय",
          active=("palika_engineer_project_detail",)),
        I("लागत अनुमान प्रतिवेदन", "palika_engineer_estimated_projects", "receipt", roles=("1", "8"), group="पालिका स्तरीय"),
        I("वडा अनुसार तुलना", "palika_engineer_ward_comparison", "scale", roles=("1", "8"), group="पालिका स्तरीय"),
        I("उपभोक्ता समिति सूची", "palika_engineer_committee_list", "users", roles=("1", "8"), group="पालिका स्तरीय"),
        I("अन्तिम मूल्याङ्कन (सबै वडा)", "palika_engineer_final_valuations", "banknote", roles=("1", "8"), group="पालिका स्तरीय"),
        I("समिति वित्तीय प्रतिवेदन", "palika_engineer_committee_financial_report", "chart-column", roles=("1", "8"), group="पालिका स्तरीय"),
    ]},
    {"key": "settings", "num": "५", "label": "सेटिङ", "items": [
        I("कर्मचारी थप्नुहोस्", "add_staff", "user-plus", roles=("1",), group="कर्मचारी"),
        I("कर्मचारी व्यवस्थापन", "manage_staff", "key-round", roles=("1",), group="कर्मचारी"),
        I("भूमिका र अनुमति", "roles_permissions", "shield-check", perms=("settings.roles",), roles=("1",), group="कर्मचारी"),
        I("स्वीकृत गर्ने अधिकारी", "uc_approvers", "stamp", perms=("uc.delegate",), roles=("1",), group="कर्मचारी"),
        I("कार्यालय सेटिङ", "office_settings", "building-2", perms=("settings.office",), roles=("1",), group="कार्यालय"),
        I("वडाहरू", "manage_wards", "map-pin", perms=("settings.office",), roles=("1",), group="कार्यालय"),
        I("आर्थिक वर्ष", "manage_fiscal_years", "calendar-days", roles=("1",), active=("edit_fiscal_year",), group="कार्यालय"),
        I("पत्रका ढाँचा", "letter_templates", "file-pen-line", perms=("letters.templates",), roles=("1",), group="कार्यालय"),
        I("क्षेत्र / उपक्षेत्र", "sector_settings", "layers", perms=("settings.sectors",), roles=("1",), group="योजना र बजेट"),
        I("बजेट प्रकार", "manage_budget_types", "coins", roles=("1",), active=("edit_budget_type",), group="योजना र बजेट"),
        I("उपलब्धि सूचक", "output_settings", "ruler", perms=("settings.outputs",), roles=("1",), group="योजना र बजेट"),
        I("खरिद प्रकार", "manage_procurement_types", "file-text", roles=("1",), active=("edit_procurement_type",), group="खरिद"),
        I("खरिद विधि सीमा", "app_limits", "scale", perms=("settings.procurement",), roles=("1",), group="खरिद"),
        I("कर शीर्षक", "tax_heads", "receipt", perms=("settings.tax",), roles=("1",), group="खरिद"),
        I("SMS / इमेल सूचना", "alerts", "bell-ring", perms=("alerts.manage",), roles=("1",), group="प्रणाली"),
        I("ब्याकअप", "backups", "database", perms=("backup.manage",), roles=("1",), group="प्रणाली"),
        I("गतिविधि लग", "activity_log", "history", roles=("1",), group="प्रणाली"),
    ]},
]

PATH_SECTION = [  # मेनुमा नभएका पेज (फारम, विवरण) कुन खण्डमा
    ("/Projects/Budget", "budget"), ("/Projects/APP", "budget"), ("/Projects/add", "budget"), ("/Projects/edit_project", "budget"),
    ("/Projects/import_excel", "budget"), ("/Projects/view_projects", "budget"),
    ("/Projects/Revenue", "revenue"),
    ("/Projects/Reports", "reports"), ("/Projects/Retention", "reports"), ("/Projects/AuditPack", "reports"),
    ("/Projects/Settings", "settings"), ("/Projects/Backups", "settings"), ("/Projects/Alerts", "settings"),
    ("/Accounts/Admin", "settings"), ("/Letters", "settings"),
    ("/Projects/Dashboard", "main"), ("/Projects/YearEnd", "main"), ("/Accounts/MyWork", "main"),
    ("/Projects/", "procure"), ("/UserCommittee", "procure"), ("/Bidding", "procure"), ("/Quatation", "procure"),
]


def _visible(it, t, P):
    if it["roles"] and t not in it["roles"]:
        return False
    if it["not_roles"] and t in it["not_roles"]:
        return False
    if it["perms"] and not any(p in P for p in it["perms"]):
        return False
    return True


def build(request, t, P, home):
    current = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
    GET = request.GET
    out, active_key = [], None
    for sec in SECTIONS:
        items = []
        for it in sec["items"]:
            if not _visible(it, t, P):
                continue
            name = home if it["url_name"] == "__home__" else it["url_name"]
            if it["url_name"] == "__home__" and home in ("my_work", "usercommittee_workflow"):
                continue
            try:
                url = reverse(name) + (f"?{it['query']}" if it["query"] else "")
            except NoReverseMatch:
                continue
            act = current == name or current in it["active"] or bool(it["prefix"] and current.startswith(it["prefix"]))
            if act and it["match"]:
                act = all((GET.get(k) or "") == v for k, v in it["match"].items()) or (
                    current != name and current in it["active"])
            items.append({"label": it["label"], "url": url, "icon": it["icon"], "group": it["group"], "active": act})
        if not items:
            continue
        # एउटै पेज दुई खण्डमा (योजना vs खर्च) — पहिलो मिलेकोमा मात्र सक्रिय
        if any(x["active"] for x in items) and active_key is None:
            active_key = sec["key"]
        groups, by = [], {}
        for x in items:                       # एउटै नामका उप-समूह एकै ठाउँमा (पहिलो देखिएको क्रममा)
            if x["group"] not in by:
                by[x["group"]] = {"label": x["group"], "items": []}
                groups.append(by[x["group"]])
            by[x["group"]]["items"].append(x)
        out.append({"key": sec["key"], "num": sec["num"], "label": sec["label"], "groups": groups,
                    "first_url": items[0]["url"], "count": len(items)})
    if active_key is None:
        path = request.path
        for prefix, key in PATH_SECTION:
            if path.startswith(prefix) and any(s["key"] == key for s in out):
                active_key = key
                break
    keys = [s["key"] for s in out]
    if active_key not in keys:
        active_key = "main"
    # सक्रिय खण्ड बाहेकका खण्डमा "active" नदेखाउने
    for s in out:
        s["active"] = s["key"] == active_key
        if not s["active"]:
            for g in s["groups"]:
                for x in g["items"]:
                    x["active"] = False
    active = next((s for s in out if s["active"]), out[0] if out else None)
    return {"sections": out, "active": active}
