"""
उपभोक्ता समिति कार्यप्रवाह (workflow) — the steps every user-committee project
goes through, and the state of each step for one project.

States used by the tracker:
    done     – step finished                       (green)
    current  – the next step to work on             (blue ring)
    warning  – needs attention (e.g. म्याद नाघेको)    (orange)
    pending  – not reached yet                      (grey)
    optional – optional step not used               (dash)
"""
from datetime import date

from django.urls import reverse

from .models import DocumentPrint

# key -> (short column header, full label)
STEP_INFO = {
    "project": ("दर्ता", "योजना दर्ता"),
    "committee": ("समिति", "उपभोक्ता समिति गठन"),
    "estimate": ("लागत", "लागत अनुमान"),
    "sifaris_agreement": ("सिफारिस", "वडा सिफारिस (सम्झौताका लागि)"),
    "approval": ("स्वीकृत", "रुजु / स्वीकृत"),
    "agreement": ("सम्झौता", "सम्झौता र कार्यादेश"),
    "valuation": ("मूल्याङ्कन", "अन्तिम मूल्याङ्कन"),
    "public_audit": ("सा. परीक्षण", "सार्वजनिक परीक्षण / सुनुवाइ र अनुगमन"),
    "sifaris_payment": ("भु. सिफारिस", "वडा सिफारिस (काम सम्पन्न / भुक्तानी)"),
    "final_tippani": ("टिप्पणी", "अन्तिम भुक्तानी टिप्पणी"),
    "handover": ("हस्तान्तरण", "हस्तान्तरण"),
}

# Two ways a palika runs उपभोक्ता समिति work (Palika.uc_mode, overridable per project):
#   municipal – पालिका केन्द्रित: the palika office makes the agreement and pays; the ward's
#               सिफारिस (portal or uploaded scan) is required before the agreement and before
#               the final payment; रुजु/स्वीकृत by the CAO or an officer he delegates.
#   ward      – वडा प्रत्यायोजित: the ward runs the whole process; स्वीकृत by the वडा अध्यक्ष.
# काम प्रगति (फोटो/निरीक्षण) is never a step: optional, shown separately.
MODE_STEPS = {
    "municipal": ["project", "committee", "estimate", "sifaris_agreement", "approval", "agreement",
                  "valuation", "public_audit", "sifaris_payment", "final_tippani", "handover"],
    "ward": ["project", "committee", "estimate", "approval", "agreement", "valuation", "public_audit",
             "final_tippani", "handover"],
}
MODE_LABELS = {"municipal": "पालिका केन्द्रित", "ward": "वडा प्रत्यायोजित"}

# table columns: every step of either mode, in order (a ward-mode row leaves the
# two सिफारिस columns empty)
COLUMNS = [(key, STEP_INFO[key][0], STEP_INFO[key][1]) for key in MODE_STEPS["municipal"]]

AGREEMENT_DOCS = [
    (DocumentPrint.CONTRACT, "सम्झौता पत्र", "print_documents"),
    (DocumentPrint.TIPPANI, "टिप्पणी", "print_tippani"),
    (DocumentPrint.BANK_LETTER, "बैंक पत्र", "print_bank_letter"),
    (DocumentPrint.WORK_ORDER, "कार्यादेश", "print_work_order"),
]


NEPALI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def bs_date(d):
    """AD date -> 'YYYY-MM-DD' in Bikram Sambat with Nepali digits ('' if unknown)."""
    if not d:
        return ""
    try:
        from nepali.date_converter import converter

        y, m, dd = converter.english_to_nepali(d.year, d.month, d.day)
        return f"{y}-{m:02d}-{dd:02d}".translate(NEPALI_DIGITS)
    except Exception:
        return str(d)


def sector_note(project):
    """' · क्षेत्र › उपक्षेत्र' (नभए '')."""
    if not project.sector_id:
        return ""
    return f" · {project.sector.name}" + (f" › {project.subsector.name}" if project.subsector_id else "")


def _rel(obj, name):
    """Reverse one-to-one access that returns None instead of raising."""
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _link(label, url_name, *args, primary=False, new_tab=False, query=""):
    url = reverse(url_name, args=args) + (f"?{query}" if query else "")
    return {"label": label, "url": url, "primary": primary, "new_tab": new_tab}


def _form(label, url_name, *args, primary=True):
    """An action that opens a small form inside the panel (HTMX) instead of a new page."""
    return {"label": label, "url": reverse(url_name, args=args), "primary": primary, "new_tab": False, "inline": True}


def _modal(label, url_name, *args, primary=True, icon=""):
    """An action that opens in the page-wide modal (HTMX)."""
    return {"label": label, "url": reverse(url_name, args=args), "primary": primary, "new_tab": False,
            "modal": True, "icon": icon}


def can_approve(user, project, mode):
    """Who may do रुजु/स्वीकृत for this project (अनुमति: accounts/permissions.py).

    - "uc.approve": CAO, Admin, वा CAO ले प्रत्यायोजन गरेका अधिकृत — सबै योजना, दुवै तरिका
    - "uc.approve_ward": वडा अध्यक्ष — वडा प्रत्यायोजित तरिकाका, आफ्नै वडाका योजना
    """
    from accounts.permissions import has_perm

    if not getattr(user, "is_authenticated", False):
        return False
    if has_perm(user, "uc.approve"):
        return True
    if mode == "ward" and has_perm(user, "uc.approve_ward"):
        from accounts.models import WardChairperson

        return WardChairperson.objects.filter(admin=user, ward_id=project.ward_id).exists()
    return False


def approver_identity(user, mode):
    """(name, post) recorded on the approval."""
    from accounts.models import UserPermission
    from accounts.permissions import ROLE_LABEL

    name = user.get_full_name() or user.mobile
    for attr in ("cao", "wardchairperson", "admin", "planningofficer", "engineer", "palikaengineer"):
        prof = getattr(user, attr, None)
        if prof is not None and getattr(prof, "name", None):
            name = prof.name
            break
    if user.user_type == "2":
        post = "प्रमुख प्रशासकीय अधिकृत"
    elif user.user_type == "9":
        post = "वडा अध्यक्ष"
    elif UserPermission.objects.filter(user=user, perm="uc.approve").exists():
        post = "प्रत्यायोजित अधिकृत"
    else:
        post = ROLE_LABEL.get(user.user_type, "अधिकृत").split(" (")[0]
    return name, post


def sifaris_note(rec):
    if not rec:
        return ""
    how = "पोर्टलबाट" if getattr(rec, "source", "portal") == "portal" else "अपलोड गरिएको"
    no = f" · च.नं. {rec.chalani_number}" if getattr(rec, "chalani_number", None) else ""
    return how + no


def sifaris_view_action(rec, project, portal_url_name):
    if getattr(rec, "source", "portal") == "upload" and rec.document:
        return {"label": "सिफारिस हेर्नुहोस्", "url": rec.document.url, "primary": False, "new_tab": True}
    return _link("सिफारिस पत्र", portal_url_name, project.id, new_tab=True)


def add_next(url, return_to):
    from urllib.parse import quote

    return url + ("&" if "?" in url else "?") + "next=" + quote(return_to, safe="/")


def with_next(steps, return_to):
    """Add ?next=<return_to> to the form links (not print links) so saving a form
    brings the user back to the workflow page."""
    from urllib.parse import quote

    if not return_to:
        return steps
    for st in steps:
        for a in st.get("actions", []):
            if not a["new_tab"] and not a.get("inline") and not a.get("modal"):
                a["url"] = add_next(a["url"], return_to)
    return steps


def _plan_gate(project):
    from projects.procurement import plan_gate

    return plan_gate(project)


def _gate_action(project):
    from projects.procurement import gate_action

    return gate_action(project)


def project_workflow(project, user_type=None, user=None):
    """Return (steps, summary) for one project, following its mode (पालिका/वडा).

    Each step: {n, key, label, state, date, note, actions:[{label,url,primary,new_tab,inline?}]}
    `project` should come from workflow_queryset() so related rows are prefetched.
    """
    from projects.models import project_uc_mode

    mode = project_uc_mode(project)
    committee = _rel(project, "user_committee")
    estimate = _rel(project, "cost_estimate")
    recommendation = _rel(project, "ward_recommendation")
    approval = _rel(project, "uc_approval")
    final = _rel(project, "final_payment")
    completion = _rel(project, "completion_recommendation")
    prints = {}
    for p in project.document_prints.all():
        prints.setdefault(p.doc_type, p)
    photos = list(project.timelines.all())
    inspections = list(project.inspection_notes.all())
    from accounts.permissions import role_perms, user_perms

    P = user_perms(user) if user is not None else role_perms(user_type)
    can_upload = "uc.sifaris_upload" in P  # palika office / ward staff upload a paper सिफारिस
    municipal = mode == "municipal"

    s = {}

    # योजना दर्ता
    s["project"] = {"done": True, "date": None,
                    "note": (project.fiscalyear.name if project.fiscalyear else "") + f" · {MODE_LABELS[mode]}"
                            + sector_note(project),
                    "actions": [_link("योजना सम्पादन", "edit_project", project.id)] if "project.manage" in P else []}

    # समिति गठन
    actions = []
    if committee:
        if "uc.committee" in P:
            actions.append(_link("समिति सम्पादन", "edit_usercommittee", committee.id))
            actions.append(_link("म्याद थप", "extend_usercommittee_date", committee.id))
        if P & {"uc.member_docs", "uc.committee"} or can_approve(user, project, mode):
            actions.append(_modal("सदस्य र कागजात", "uc_committee_review", project.id, primary=False))
    gate = "" if committee else _plan_gate(project)
    if gate:
        actions = [_gate_action(project)] if P & {"app.manage", "app.approve", "app.view"} else []
    elif not committee and "uc.committee" in P:
        actions.append(_link("समिति गठन गर्नुहोस्", "add_usercommittee_for_project", project.id, primary=True))
    s["committee"] = {"done": bool(committee), "date": committee.formation_date if committee else None,
                      "note": committee.name if committee else gate, "actions": actions}

    # लागत अनुमान
    actions = []
    if estimate and "uc.estimate_edit" in P and not approval:
        actions.append(_link("लागत सम्पादन", "edit_cost_estimate", estimate.id))
    elif not estimate and "uc.estimate" in P:   # समिति गठनअघि वा पछि — जुनसुकै क्रममा
        actions.append(_link("लागत अनुमान थप्नुहोस्", "add_cost_estimate_for_project", project.id, primary=True))
    if estimate and estimate.document:
        actions.append({"label": "📎 लागत अनुमान कागजात", "url": estimate.document.url, "primary": False, "new_tab": True})
    s["estimate"] = {"done": bool(estimate), "date": None,
                     "note": f"रु. {estimate.total_cost:,.0f}" if estimate else ("समिति गठनसँगै वा अघि भर्न सकिन्छ" if not committee else ""),
                     "actions": actions}

    # वडा सिफारिस (सम्झौताका लागि) — municipal only; वडाको सिफारिस पत्र अपलोड (पोर्टल बटन हटाइयो)
    actions = []
    if recommendation:
        actions.append(sifaris_view_action(recommendation, project, "print_ward_recommendation"))
    elif estimate and committee:
        if can_upload:
            actions.append(_form("सिफारिस अपलोड गर्नुहोस्", "uc_sifaris_upload", project.id, "agreement", primary=True))
    s["sifaris_agreement"] = {"done": bool(recommendation),
                              "date": recommendation.recommendation_date if recommendation else None,
                              "note": sifaris_note(recommendation) or ("वडाको सिफारिस पत्र अपलोड गर्नुहोस्" if estimate and committee else ""),
                              "actions": actions}

    # रुजु / स्वीकृत
    actions = []
    ready = bool(estimate) and (bool(recommendation) or not municipal)
    if not approval and ready and user is not None and can_approve(user, project, mode):
        actions.append(_modal("रुजु / स्वीकृत गर्नुहोस्", "uc_approve", project.id, icon="stamp"))
    elif approval and (P & {"uc.member_docs", "uc.approve"} or can_approve(user, project, mode)):
        actions.append(_modal("स्वीकृत विवरण", "uc_approve", project.id, primary=False))
    if approval:
        note = f"{approval.approver_name} ({approval.approver_post})"
    elif ready:
        note = ("वडा अध्यक्ष वा प्रमुख प्रशासकीय अधिकृतबाट" if mode == "ward"
                else "प्रमुख प्रशासकीय अधिकृत, प्रत्यायोजित अधिकृत वा Admin बाट")
    else:
        note = ""
    s["approval"] = {"done": bool(approval), "date": approval.approved_at.date() if approval else None,
                     "note": note, "remarks": approval.remarks if approval else "", "actions": actions}

    # सम्झौता र कार्यादेश (documents printed) — after स्वीकृत
    printed = [d for d, _l, _u in AGREEMENT_DOCS if d in prints]
    actions = []
    if (approval or printed) and "uc.agreement_print" in P:
        for doc, label, url_name in AGREEMENT_DOCS:
            actions.append(_link(("✓ " if doc in prints else "") + label, url_name, project.id, new_tab=True,
                                 primary=doc not in prints))
    if (approval or printed) and committee is not None and P & {"uc.agreement_print", "uc.committee"}:
        actions.append(_link(("✓ " if committee.has_bank_account else "") + "बैंक खाता विवरण", "uc_bank_account",
                             project.id, primary=False))
    first_print = min((prints[d].printed_at for d in printed), default=None)
    s["agreement"] = {"done": DocumentPrint.CONTRACT in prints and DocumentPrint.WORK_ORDER in prints,
                      "date": first_print.date() if first_print else None,
                      "note": f"{len(printed)}/{len(AGREEMENT_DOCS)} कागजात" if (approval or printed) else "",
                      "actions": actions}

    # काम प्रगति (photos / inspection) — optional, not a step
    stage_names = dict(getattr(type(photos[0]), "STAGE_CHOICES", ())) if photos else {}
    progress_actions = [_link("फोटो टाइमलाइन", "project_timeline", project.id)]
    if "uc.progress_photo" in P and user_type == "7":
        progress_actions.insert(0, _link("फोटो अपलोड", "ward_engineer_project_photos", project.id, primary=True))
    if "uc.inspection" in P and user_type == "8":
        progress_actions.insert(0, _link("निरीक्षण टिप्पणी", "add_site_inspection_note", project.id, primary=True))
        progress_actions.append(_link("विवरण", "palika_engineer_project_detail", project.id))
    progress = {
        "photos": len(photos),
        "inspections": len(inspections),
        "stages": [stage_names.get(st, "") for st in sorted({p.stage for p in photos if p.stage})],
        "last_date_bs": bs_date(photos[-1].created_at.date()) if photos else "",
        "actions": progress_actions,
    }

    # किस्ता भुक्तानी (पेश्की / रनिङ) — ऐच्छिक, सम्झौतापछि, अन्तिम भुक्तानीअघि
    inst = list(project.installments.all())
    inst_total = sum((i.amount for i in inst), 0)
    installments = {
        "show": bool(inst) or bool(approval or printed),
        "count": len(inst), "total": inst_total,
        "last": inst[-1].label if inst else "",
        "url": reverse("uc_installments", args=[project.id]),
        "can_view": bool(P & {"uc.valuation", "uc.payment_print"}),
        "can_add": "uc.valuation" in P and not final,
    }

    # अन्तिम मूल्याङ्कन
    actions = []
    if final and not final.tippani_printed and "uc.valuation" in P:
        actions.append(_link("मूल्याङ्कन सम्पादन", "edit_final_valuation", final.id))
    if final and "uc.valuation" in P:
        n_out = len(project.outputs.all())
        actions.append(_link(("✓ " if n_out else "") + "भौतिक उपलब्धि", "project_outputs", project.id,
                             primary=not n_out))
    elif not final and estimate and "uc.valuation" in P and (approval or printed):
        actions.append(_link("अन्तिम मूल्याङ्कन थप्नुहोस्", "add_final_valuation", primary=True, query=f"project={project.id}"))
    if (approval or printed) and P & {"mb.view", "mb.measure"}:
        actions.append(_link("नापी किताब", "mb_page", project.id))
    if final and final.document:
        actions.append({"label": "📎 मूल्याङ्कन कागजात", "url": final.document.url, "primary": False, "new_tab": True})
    note = f"रु. {final.final_evaluation:,.0f}" if final else ""
    if inst:
        note += (" · " if note else "") + f"{len(inst)} किस्ता रु. {inst_total:,.0f} कट्टी हुने"
    s["valuation"] = {"done": bool(final), "date": final.application_date if final else None,
                      "note": note, "actions": actions}

    # सार्वजनिक परीक्षण / सुनुवाइ र अनुगमन — पालिकाको सेटिङअनुसार अनिवार्य वा ऐच्छिक
    audit = _rel(project, "public_audit")
    audit_required = audit_is_required()
    actions = []
    if "uc.public_audit" in P and (final or approval or printed or audit):
        actions.append(_link("विवरण सम्पादन" if audit else "सार्वजनिक परीक्षण विवरण भर्नुहोस्", "uc_public_audit",
                             project.id, primary=not audit))
    if audit:
        actions.append(_link("मुचुल्का / प्रतिवेदन", "uc_print_public_audit", project.id, new_tab=True))
    if audit:
        note = f"{audit.participants_total} जना सहभागी (महिला {audit.women_pct}%)"
        if audit.monitoring_finding:
            note += f" · अनुगमन: {audit.get_monitoring_finding_display()}"
    else:
        note = "अनिवार्य — भुक्तानीअघि" if audit_required else "ऐच्छिक"
    s["public_audit"] = {"done": bool(audit and audit.date), "date": audit.date if audit else None,
                         "note": note, "actions": actions, "optional": not audit_required}

    # वडा सिफारिस (काम सम्पन्न / भुक्तानी) — municipal only; वडाको सिफारिस पत्र अपलोड (पोर्टल बटन हटाइयो)
    actions = []
    if completion:
        actions.append(sifaris_view_action(completion, project, "print_completion_recommendation"))
    elif final:
        if can_upload:
            actions.append(_form("सिफारिस अपलोड गर्नुहोस्", "uc_sifaris_upload", project.id, "payment", primary=True))
    s["sifaris_payment"] = {"done": bool(completion),
                            "date": completion.recommendation_date if completion else None,
                            "note": sifaris_note(completion) or ("वडाको सिफारिस पत्र अपलोड गर्नुहोस्" if final else ""),
                            "actions": actions}

    # अन्तिम भुक्तानी टिप्पणी — municipal: after the payment सिफारिस
    actions = []
    audit_ok = not audit_required or bool(audit and audit.date)
    if final and (final.tippani_printed or ((completion or not municipal) and audit_ok)) and "uc.payment_print" in P:
        actions.append(_link("अन्तिम टिप्पणी", "usercommittee_print_final_tippani", project.id, new_tab=True,
                             primary=not final.tippani_printed))
    s["final_tippani"] = {"done": bool(final and final.tippani_printed), "date": None,
                          "note": "छापिएपछि मूल्याङ्कन लक हुन्छ" if final and not final.tippani_printed else "",
                          "actions": actions}

    # हस्तान्तरण
    actions = []
    if final and (completion or not municipal) and "uc.payment_print" in P:
        actions.append(_link("हस्तान्तरण पत्र", "print_handover_letter", project.id, new_tab=True,
                             primary=DocumentPrint.HANDOVER not in prints))
    handover = prints.get(DocumentPrint.HANDOVER)
    s["handover"] = {"done": bool(handover), "date": handover.printed_at.date() if handover else None,
                     "note": "", "actions": actions}

    keys = MODE_STEPS[mode]

    # ---- older records: a later step done means the earlier ones happened ----
    # (no print log / approval record existed before) — not for सिफारिस, which is a real document
    later_done = False
    for key in reversed(keys):
        info = s[key]
        if info["done"] and key != "estimate":   # लागत अनुमान समितिअघि पनि भर्न मिल्ने — त्यसैले समिति "भएको" मानिँदैन
            later_done = True
        elif later_done and not key.startswith("sifaris") and key != "public_audit":
            info["done"] = True
            info["note"] = (info["note"] + " · " if info["note"] else "") + "पुरानो अभिलेख"

    # ---- states ----
    overdue = bool(committee and committee.is_overdue) if committee else False
    steps, current = [], None
    for n, key in enumerate(keys, start=1):
        info = s[key]
        if info["done"]:
            state = "done"
        elif info.get("optional"):
            state = "optional"
        elif current is None:
            current = n
            state = "warning" if overdue else "current"
        else:
            state = "pending"
        short, label = STEP_INFO[key]
        steps.append({"n": n, "key": key, "short": short, "label": label, "state": state,
                      "date_bs": bs_date(info.get("date")), **info})

    all_done = current is None
    cur = next((st for st in steps if st["n"] == current), None)
    # समिति र लागत अनुमान जुनसुकै क्रममा: समिति बाँकी रहँदा लागत अनुमान पनि "हालको" चरण
    if cur and cur["key"] == "committee":
        for st in steps:
            if st["key"] == "estimate" and st["state"] == "pending":
                st["state"] = cur["state"]
    summary = {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "progress": progress,
        "installments": installments,
        "current": current,
        "current_key": cur["key"] if cur else "",
        "current_label": cur["label"] if cur else "",
        "done_count": sum(1 for st in steps if st["state"] == "done"),
        "total": len(steps),
        "completed": all_done,
        "overdue": overdue and not all_done,
        "extended": bool(committee and committee.extended_date),
        "deadline": committee.deadline if committee else None,
        "deadline_bs": bs_date(committee.deadline) if committee else "",
        "days_left": committee.days_left if committee else None,
        "days_late": abs(committee.days_left) if committee and committee.days_left is not None and committee.days_left < 0 else 0,
    }
    return steps, summary


def audit_is_required():
    from django.db import connection

    return bool(getattr(getattr(connection, "tenant", None), "require_public_audit", False))


def row_cells(steps):
    """Steps placed under the table COLUMNS (None where this mode has no such step)."""
    by_key = {st["key"]: st for st in steps}
    return [by_key.get(key) for key, _short, _label in COLUMNS]


def open_keys(steps, summary):
    """हाल गर्न मिल्ने चरण(हरू): हालको चरण, र समिति बाँकी हुँदा लागत अनुमान पनि (समानान्तर)."""
    keys = {summary["current_key"]} if summary.get("current_key") else set()
    if summary.get("current_key") == "committee":
        keys |= {st["key"] for st in steps if st["key"] == "estimate" and st["state"] != "done"}
    return keys


def workflow_queryset():
    from projects.models import Project

    return (
        Project.objects.filter(procurement_type=1)
        .select_related("ward", "fiscalyear", "sector", "subsector", "procurement_plan", "minor", "user_committee", "cost_estimate", "ward_recommendation",
                        "uc_approval", "final_payment", "completion_recommendation", "public_audit")
        .prefetch_related("document_prints", "timelines", "inspection_notes", "installments", "outputs",
                          "user_committee__member_links__person")
        .order_by("-id")
    )


def logs_print(view, doc_type):
    """Wrap a print view: when it actually renders the document (HTTP 200),
    record a DocumentPrint so the workflow tracker marks that step done."""
    from functools import wraps

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        if getattr(response, "status_code", None) == 200:
            project_id = kwargs.get("id") or kwargs.get("project_id") or (args[0] if args else None)
            try:
                DocumentPrint.objects.create(
                    project_id=int(project_id), doc_type=doc_type,
                    printed_by=request.user if request.user.is_authenticated else None,
                )
            except (TypeError, ValueError):
                pass
        return response

    return wrapper


def uc_gate(view, need):
    """Block a print page until the workflow allows it, e.g. सम्झौता before स्वीकृत.

    need: "agreement" | "final_tippani" | "handover". Older projects that already
    printed (before these rules existed) keep working.
    """
    from functools import wraps

    from django.contrib import messages
    from django.shortcuts import redirect

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from projects.models import Project, project_uc_mode

        from accounts.permissions import has_perm

        perm = "uc.agreement_print" if need == "agreement" else "uc.payment_print"
        if not has_perm(request.user, perm):
            messages.error(request, "यो कागजात छाप्ने अनुमति तपाईंलाई छैन।")
            return redirect("usercommittee_workflow")
        pid = kwargs.get("id") or kwargs.get("project_id") or (args[0] if args else None)
        project = Project.objects.filter(id=pid).first() if str(pid).isdigit() else None
        if project is not None and project.procurement_type_id == 1:
            mode = project_uc_mode(project)
            final = _rel(project, "final_payment")
            problem = None
            if need == "agreement":
                legacy = project.document_prints.filter(
                    doc_type__in=[d for d, _l, _u in AGREEMENT_DOCS]).exists() or final is not None
                if not legacy:
                    if mode == "municipal" and not _rel(project, "ward_recommendation"):
                        problem = "सम्झौता अघि वडा सिफारिस पत्र अपलोड गर्नुपर्छ।"
                    elif not _rel(project, "uc_approval"):
                        problem = "सम्झौता अघि रुजु / स्वीकृत हुनुपर्छ।"
            elif need == "final_tippani":
                if final is not None and not final.tippani_printed and audit_is_required() \
                        and not getattr(_rel(project, "public_audit"), "date", None):
                    problem = "अन्तिम भुक्तानी टिप्पणी अघि सार्वजनिक परीक्षण चाहिन्छ।"
                elif mode == "municipal" and final is not None and not final.tippani_printed \
                        and not _rel(project, "completion_recommendation"):
                    problem = "अन्तिम भुक्तानी टिप्पणी अघि वडाको काम सम्पन्न / भुक्तानी सिफारिस चाहिन्छ।"
            elif need == "handover":
                if final is None:
                    problem = "हस्तान्तरण अघि अन्तिम मूल्याङ्कन चाहिन्छ।"
                elif audit_is_required() and not getattr(_rel(project, "public_audit"), "date", None) \
                        and not project.document_prints.filter(doc_type=DocumentPrint.HANDOVER).exists():
                    problem = "हस्तान्तरण अघि सार्वजनिक परीक्षण चाहिन्छ।"
                elif mode == "municipal" and not _rel(project, "completion_recommendation"):
                    problem = "हस्तान्तरण अघि वडाको काम सम्पन्न सिफारिस चाहिन्छ।"
            if problem:
                messages.error(request, f"“{project.name}”: {problem}")
                return redirect("usercommittee_workflow")
        return view(request, *args, **kwargs)

    return wrapper
