"""सोझै खरिद / अमानत / संस्था-समिति — सूची, चरणअनुसार पेज (फारम), छाप्ने कागजात."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Ward
from accounts.permissions import has_perm, user_perms
from accounts.wards import sorted_wards

from . import minor as mn
from .models import FiscalYear, MinorPayment, MinorPrint, MinorProcurement, MinorQuote

VIEW = {"minor.view", "minor.manage", "minor.approve", "minor.print"}


def _user_wards(user):
    from usercommittee.views_workflow import _user_wards as uw

    return uw(user)


def _money(raw):
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "").strip().translate(str.maketrans("०१२३४५६७८९", "0123456789")))
    except (InvalidOperation, ValueError):
        return None


def _date(raw):
    from biddings.views_workflow import to_ad

    return to_ad(raw) if raw else None


def _scoped(request):
    qs = mn.workflow_queryset()
    wards = _user_wards(request.user)
    if wards is not None:
        qs = qs.filter(ward_id__in=wards)
    return qs, wards


# ---------------------------------------------------------------- सूची
@login_required
def minor_list(request):
    if not user_perms(request.user) & VIEW:
        return redirect("unauthorized")
    qs, wards = _scoped(request)
    method = request.GET.get("method", "")
    method = method if method in mn.STEPS else ""
    if method == "sanstha":       # संस्था / समिति: छुट्टै पूरा कार्यप्रवाह (views_sanstha)
        from django.urls import reverse
        keep = request.GET.copy()
        keep.pop("method", None)
        return redirect(reverse("sanstha_workflow") + (f"?{keep.urlencode()}" if keep else ""))
    f = {k: (request.GET.get(k) or "").strip() for k in ("fiscalyear", "ward", "q", "stage")}
    from .fiscal import default_fy_param

    f["fiscalyear"] = default_fy_param(request)   # पूर्वनिर्धारित: चालु आ.व.
    if method:
        qs = qs.filter(procurement_type__code=method)
    if f["fiscalyear"].isdigit():
        qs = qs.filter(fiscalyear_id=f["fiscalyear"])
    if f["ward"].isdigit():
        qs = qs.filter(ward_id=f["ward"])
    if f["q"]:
        qs = qs.filter(Q(name__icontains=f["q"]) | Q(minor__quotes__name__icontains=f["q"])).distinct()
    rows = []
    for p in qs.order_by("-id"):
        steps, s = mn.workflow(p)
        rows.append({"p": p, "steps": steps, "summary": s, "m": mn.minor_of(p),
                     "label": mn.METHOD_LABEL.get(s["method"], "")})
    counts = mn.summary_counts(rows)
    st = f["stage"]
    if st == "running":
        rows = [r for r in rows if not r["summary"]["completed"]]
    elif st == "completed":
        rows = [r for r in rows if r["summary"]["completed"]]
    elif st == "to_approve":
        rows = [r for r in rows if r["summary"]["current_key"] == "approval"]
    elif st == "overdue":
        rows = [r for r in rows if r["summary"]["overdue"]]
    elif st:
        rows = [r for r in rows if r["summary"]["current_key"] == st]
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    keep = request.GET.copy()
    keep.pop("page", None)
    return render(request, "projects/minor_list.html", {
        "page": page, "rows": page.object_list, "counts": counts, "f": f, "method": method,
        "method_label": mn.METHOD_LABEL.get(method, "सोझै खरिद / अमानत / संस्था-समिति"),
        "methods": mn.METHOD_LABEL.items(), "columns": mn.columns(method) if method else None,
        "fiscal_years": FiscalYear.objects.order_by("-name"), "qs": keep.urlencode(),
        "all_wards": sorted_wards(Ward.objects.filter(id__in=wards) if wards is not None else None),
    })


# ---------------------------------------------------------------- चरणअनुसार पेज
def _project(request, project_id):
    qs, _w = _scoped(request)
    return get_object_or_404(qs, id=project_id)


@login_required
def minor_detail(request, project_id):
    P = user_perms(request.user)
    if not P & VIEW:
        return redirect("unauthorized")
    project = _project(request, project_id)
    if mn.method_of(project) == "sanstha":
        from django.urls import reverse
        return redirect(reverse("sanstha_workflow") + f"?open={project.id}")
    posted, failed = {}, ""
    if request.method == "POST":
        errors = _post(request, project, P)
        if errors is None:
            return redirect("minor_detail", project.id)
        posted, failed = request.POST, request.POST.get("action", "")
        project = _project(request, project_id)
    from .procurement import limits

    steps, s = mn.workflow(project)
    m = mn.minor_of(project)
    pays = list(m.payments.all()) if m else []
    plan = getattr(project, "procurement_plan", None)
    L = limits()
    prints = {}
    for pr_ in (m.prints.all() if m else []):
        prints[pr_.doc_type] = pr_
    fin = mn.final_payment(m)
    remaining = (mn.payment_cap(m) - mn.paid(m, True)) if m else None
    bsx = lambda d: _bs(d) if d else ""  # noqa: E731
    v = {
        "estimate_amount": m.estimate_amount if m else (plan.estimated_cost if plan else project.budget),
        "estimate_date": bsx(m.estimate_date) if m else _bs(date.today()),
        "notice_date": bsx(m.notice_date) if m and m.notice_date else _bs(date.today()),
        "notice_ref": m.notice_ref if m else "",
        "order_no": m.order_no if m else "", "order_date": bsx(m.order_date) if m and m.order_date else _bs(date.today()),
        "order_amount": (m.order_amount if m and m.order_amount else (m.selected.amount if m and m.selected else
                                                                      (m.estimate_amount if m else ""))),
        "due_date": bsx(m.due_date) if m and m.due_date else "", "in_charge": m.in_charge if m else "",
        "completed_on": bsx(m.completed_on) if m and m.completed_on else _bs(date.today()),
        "completion_value": m.completion_value if m and m.completion_value else (m.order_amount if m else ""),
        "completion_note": m.completion_note if m else "",
        "date": bsx(fin.date) if fin else _bs(date.today()), "bill_no": fin.bill_no if fin else "",
        "gross": fin.gross if fin else (remaining if remaining and remaining > 0 else ""),
        **{k: (fin.taxes.get(k, "") if fin else "") for k, _l in mn.TAX_FIELDS},
    }
    if posted:
        v.update({k: posted.get(k) for k in posted if k != "csrfmiddlewaretoken"})
    from .fiscal import is_old, old_message

    if is_old(project):     # अघिल्लो आ.व.: हेर्न / छाप्न मात्र
        P = frozenset(x for x in P if x in ("minor.view", "minor.print"))
    return render(request, "projects/minor_detail.html", {
        "fy_locked": is_old(project), "fy_lock_msg": old_message(project) if is_old(project) else "",
        "v": v, "remaining": remaining,
        "project": project, "m": m, "steps": steps, "s": s, "method": s["method"],
        "method_label": mn.METHOD_LABEL.get(s["method"], ""), "plan": plan, "P": P,
        "quotes": list(m.quotes.all()) if m else [], "pays": pays, "fin": mn.final_payment(m),
        "paid": mn.paid(m), "paid_running": mn.paid(m, True), "cap": mn.payment_cap(m) if m else None,
        "tax_fields": mn.TAX_FIELDS, "min_quotes": mn.MIN_QUOTES.get(s["method"], 0), "prints": prints,
        "today_bs": _bs(date.today()), "can_manage": "minor.manage" in P, "can_approve": "minor.approve" in P,
        "can_print": "minor.print" in P, "L": L, "d": posted, "failed": failed,
        "errors": errors if request.method == "POST" else [],
        "direct_cap": (L.consult_direct_limit if plan and plan.nature == "consulting" else L.direct_limit),
        "budget_note": _budget_note(project),
        "firm_options": _firm_options(s["method"]),
    })


def _firm_options(method):
    from . import firms as fm

    return fm.options(["organization"] if method == "sanstha" else ["supplier", "contractor", "consultant"])


def _bs(d):
    from biddings.views_workflow import to_bs

    return to_bs(d)


def _budget_note(project):
    from .budget import budget_note

    try:
        return budget_note(project)
    except Exception:
        return ""


def _post(request, project, P):
    """फारम सुरक्षित — त्रुटि भए सूची, सफल भए None."""
    from .budget import check_payment
    from .budget import spent as budget_spent
    from .procurement import limits, plan_gate

    a = request.POST.get("action", "")
    m = mn.minor_of(project)
    method = mn.method_of(project)
    need = {"estimate": "minor.manage", "notice": "minor.manage", "quote_add": "minor.manage", "quote_del": "minor.manage",
            "approve": "minor.approve", "order": "minor.manage", "pay": "minor.manage", "pay_del": "minor.manage",
            "completion": "minor.manage", "final": "minor.manage"}.get(a)
    if need is None or need not in P:
        return ["यो काम गर्ने अनुमति छैन।"]
    if a != "estimate" and m is None:
        return ["पहिले लागत अनुमान दर्ता गर्नुहोस्।"]
    fin = mn.final_payment(m)
    if fin is not None and a not in ("final",):
        return ["अन्तिम भुक्तानी भइसकेको छ — अब परिवर्तन गर्न मिल्दैन।"]
    if fin is not None and m.prints.filter(doc_type="payment").exists():
        return ["भुक्तानी टिप्पणी छापिइसकेकाले अन्तिम भुक्तानी बदल्न मिल्दैन।"]
    approved = bool(m and m.approved_at)
    errors = []

    if a == "estimate":
        if approved:
            return ["स्वीकृत भइसकेपछि लागत अनुमान बदल्न मिल्दैन।"]
        if m is None and (gate := plan_gate(project)):
            return [gate]
        amount, day = _money(request.POST.get("estimate_amount")), _date(request.POST.get("estimate_date"))
        if day is None:
            errors.append("लागत अनुमान स्वीकृत मिति भर्नुहोस् (वि.सं. YYYY-MM-DD)।")
        errors += mn.check_estimate(project, getattr(project, "procurement_plan", None), amount, limits())
        if errors:
            return errors
        obj = m or MinorProcurement(project=project, method=method, created_by=request.user)
        obj.estimate_amount, obj.estimate_date = amount, day
        if request.FILES.get("estimate_doc"):
            obj.estimate_doc = request.FILES["estimate_doc"]
        obj.save()
        messages.success(request, f"लागत अनुमान रु. {amount:,.2f} दर्ता भयो।")
        return None

    if a == "notice":
        if approved:
            return ["स्वीकृत भइसकेपछि सूचना बदल्न मिल्दैन।"]
        day = _date(request.POST.get("notice_date"))
        if day is None:
            return ["सूचना मिति भर्नुहोस्।"]
        if day < m.estimate_date:
            return ["सूचना मिति लागत अनुमान मितिभन्दा अघि हुन सक्दैन।"]
        m.notice_date, m.notice_ref = day, (request.POST.get("notice_ref") or "").strip()
        m.save(update_fields=["notice_date", "notice_ref"])
        messages.success(request, "सूचना / आशयपत्र आह्वान दर्ता भयो।")
        return None

    if a == "quote_add":
        if approved:
            return ["स्वीकृत भइसकेपछि दरभाउ / प्रस्ताव थप्न मिल्दैन।"]
        name, amount = (request.POST.get("name") or "").strip(), _money(request.POST.get("amount"))
        if not name:
            errors.append("फर्म / संस्थाको नाम लेख्नुहोस्।")
        if amount is None or amount <= 0:
            errors.append("रकम ० भन्दा बढी हुनुपर्छ।")
        if name and m.quotes.filter(name=name).exists():
            errors.append(f"“{name}” को दरभाउ / प्रस्ताव पहिले नै छ।")
        from . import firms as fm
        pan_ = (request.POST.get("pan") or "").strip()
        if pan_ and not (pan_.isdigit() and len(pan_) == 9):
            errors.append("PAN / VAT नम्बर ९ अङ्कको हुनुपर्छ।")
        if name and (e := fm.blocked(fm.find(name, pan_), name, pan_)):
            errors.append(e)
        rec = _date(request.POST.get("received_on"))
        if method == "sanstha" and m.notice_date is None:
            errors.append("पहिले सूचना / आशयपत्र आह्वान दर्ता गर्नुहोस्।")
        if errors:
            return errors
        firm = fm.find_or_create(name, pan_, (request.POST.get("address") or "").strip(),
                                 kind="organization" if method == "sanstha" else "supplier")
        MinorQuote.objects.create(minor=m, firm=firm, name=name, amount=amount, pan=(request.POST.get("pan") or "").strip(),
                                  address=(request.POST.get("address") or "").strip(), received_on=rec,
                                  remarks=(request.POST.get("remarks") or "").strip())
        messages.success(request, f"“{name}” — रु. {amount:,.2f} थपियो।")
        return None

    if a == "quote_del":
        if approved:
            return ["स्वीकृत भइसकेपछि हटाउन मिल्दैन।"]
        m.quotes.filter(id=request.POST.get("id") or 0).delete()
        return None

    if a == "approve":
        if approved:
            return ["पहिले नै स्वीकृत भइसकेको छ।"]
        quote = m.quotes.filter(id=request.POST.get("quote") or 0).first() if method in mn.MIN_QUOTES else None
        errors = mn.check_selection(m, quote)
        if errors:
            return errors
        if quote is not None and quote.amount != min(q.amount for q in m.quotes.all()) and not request.POST.get("reason"):
            return ["न्यूनतम रकम नभएको छान्दा कारण लेख्नुहोस्।"]
        from usercommittee.workflow import approver_identity

        name, post = approver_identity(request.user, "municipal")
        m.selected, m.approved_by, m.approved_at = quote, request.user, timezone.now()
        m.approver_name = f"{name} ({post})"
        m.approval_remarks = (request.POST.get("reason") or request.POST.get("remarks") or "").strip()
        m.save()
        messages.success(request, "स्वीकृत भयो।" + (f" छनौट: {quote.name} — रु. {quote.amount:,.2f}" if quote else ""))
        return None

    if a == "order":
        if not approved:
            return ["स्वीकृत भएपछि मात्र आदेश / सम्झौता।"]
        if m.payments.exists():
            return ["भुक्तानी भइसकेपछि आदेश / सम्झौता बदल्न मिल्दैन।"]
        day, due = _date(request.POST.get("order_date")), _date(request.POST.get("due_date"))
        amount = _money(request.POST.get("order_amount"))
        no = (request.POST.get("order_no") or "").strip()
        if day is None:
            errors.append("आदेश / सम्झौता मिति भर्नुहोस्।")
        elif day < m.estimate_date:
            errors.append("आदेश मिति लागत अनुमानभन्दा अघि हुन सक्दैन।")
        if due is None:
            errors.append("काम सम्पन्न / आपूर्ति गर्नुपर्ने मिति भर्नुहोस्।")
        elif day and due < day:
            errors.append("सम्पन्न गर्नुपर्ने मिति आदेश मितिभन्दा पछि हुनुपर्छ।")
        limit = mn.D(m.selected.amount) if m.selected else mn.D(m.estimate_amount)
        if amount is None or amount <= 0:
            errors.append("आदेश / सम्झौता रकम भर्नुहोस्।")
        elif amount > limit + mn.TOL:
            errors.append(f"आदेश रकम {'स्वीकृत दरभाउ / प्रस्ताव' if m.selected else 'लागत अनुमान'} रु. {limit:,.2f} भन्दा बढी हुन सक्दैन।")
        if method == "amanat" and not (request.POST.get("in_charge") or "").strip():
            errors.append("अमानतको जिम्मेवार कर्मचारी लेख्नुहोस्।")
        if errors:
            return errors
        m.order_no, m.order_date, m.due_date, m.order_amount = no, day, due, amount
        m.in_charge = (request.POST.get("in_charge") or "").strip()
        m.save()
        messages.success(request, "आदेश / सम्झौता दर्ता भयो।")
        return None

    if a in ("pay", "final"):
        if not m.order_date:
            return ["आदेश / सम्झौता भएपछि मात्र भुक्तानी।"]
        if a == "final" and not m.completed_on:
            return ["पहिले जाँचपास / काम सम्पन्न प्रतिवेदन दर्ता गर्नुहोस्।"]
        if a == "pay" and method == "direct":
            return ["सोझै खरिदमा एकमुष्ट भुक्तानी मात्र।"]
        if a == "pay" and m.completed_on and method != "amanat":
            return ["काम सम्पन्न भइसकेपछि अन्तिम भुक्तानी गर्नुहोस्।"]
        kind = "final" if a == "final" else (request.POST.get("kind") if request.POST.get("kind") in ("running", "muster", "material") else "running")
        day = _date(request.POST.get("date"))
        gross = _money(request.POST.get("gross"))
        taxes = {}
        for k, lbl in mn.TAX_FIELDS:
            v = _money(request.POST.get(k))
            if v is not None and v < 0:
                errors.append(f"{lbl} ऋणात्मक हुन सक्दैन।")
            elif v:
                taxes[k] = str(v)
        if day is None:
            errors.append("भुक्तानी मिति भर्नुहोस्।")
        elif day < m.order_date:
            errors.append("भुक्तानी मिति आदेश / सम्झौता मितिभन्दा अघि हुन सक्दैन।")
        elif a == "final" and day < m.completed_on:
            errors.append("अन्तिम भुक्तानी मिति सम्पन्न मितिभन्दा अघि हुन सक्दैन।")
        if gross is None or gross <= 0:
            errors.append("कुल रकम ० भन्दा बढी हुनुपर्छ।")
        else:
            before = mn.paid(m) - (mn.D(fin.gross) if fin else mn.ZERO)
            cap = mn.payment_cap(m)
            if before + gross > cap + mn.TOL:
                errors.append(f"कुल भुक्तानी रु. {before + gross:,.2f} {'जाँचपास' if m.completion_value else 'आदेश'} रकम रु. {cap:,.2f} भन्दा बढी भयो।")
            if mn.tax_total(taxes) > gross:
                errors.append("कट्टी कुल रकमभन्दा बढी भयो।")
            if not errors and (e := check_payment(project, budget_spent(project) - (mn.D(fin.gross) if fin else 0) + gross,
                                                  "यो भुक्तानी")):
                errors.append(e)
        if kind == "muster" and not request.POST.get("person_days"):
            errors.append("हाजिरीमा जम्मा श्रम दिन भर्नुहोस्।")
        if errors:
            return errors
        with transaction.atomic():
            obj = fin if (a == "final" and fin) else MinorPayment(minor=m, kind=kind, created_by=request.user)
            obj.date, obj.gross, obj.taxes = day, gross, taxes
            obj.net = gross - mn.tax_total(taxes)
            obj.bill_no = (request.POST.get("bill_no") or "").strip()
            obj.remarks = (request.POST.get("remarks") or "").strip()
            w = request.POST.get("workers") or ""
            obj.workers = int(w) if w.isdigit() else None
            obj.person_days = _money(request.POST.get("person_days"))
            if request.FILES.get("doc"):
                obj.doc = request.FILES["doc"]
            obj.save()
            if a == "final":
                project.status = 2
                project.save(update_fields=["status"])
        messages.success(request, f"{dict(MinorPayment.KINDS)[kind]} रु. {gross:,.2f} (खुद रु. {obj.net:,.2f}) दर्ता भयो।")
        return None

    if a == "pay_del":
        last = m.payments.exclude(kind="final").order_by("-date", "-id").first()
        if last is None or str(last.id) != request.POST.get("id"):
            return ["पछिल्लो बिल मात्र हटाउन मिल्छ।"]
        if m.completed_on:
            return ["काम सम्पन्न दर्ता भइसकेपछि हटाउन मिल्दैन।"]
        last.delete()
        messages.success(request, "बिल हटाइयो।")
        return None

    if a == "completion":
        if not m.order_date:
            return ["आदेश / सम्झौता भएपछि मात्र।"]
        day = _date(request.POST.get("completed_on"))
        value = _money(request.POST.get("completion_value"))
        if day is None:
            errors.append("सम्पन्न / आपूर्ति मिति भर्नुहोस्।")
        elif day < m.order_date:
            errors.append("सम्पन्न मिति आदेश मितिभन्दा अघि हुन सक्दैन।")
        if value is None or value <= 0:
            errors.append("जाँचपास / मूल्याङ्कन रकम भर्नुहोस्।")
        elif value > mn.D(m.order_amount) + mn.TOL:
            errors.append(f"जाँचपास रकम आदेश / सम्झौता रकम रु. {mn.D(m.order_amount):,.2f} भन्दा बढी हुन सक्दैन।")
        elif value < mn.paid(m, True) - mn.TOL:
            errors.append(f"जाँचपास रकम अहिलेसम्मको भुक्तानी रु. {mn.paid(m, True):,.2f} भन्दा कम हुन सक्दैन।")
        if not (request.POST.get("completion_note") or "").strip():
            errors.append("जाँचपास / प्रतिवेदनको विवरण लेख्नुहोस्।")
        if errors:
            return errors
        m.completed_on, m.completion_value = day, value
        m.completion_note = request.POST.get("completion_note").strip()
        if request.FILES.get("completion_doc"):
            m.completion_doc = request.FILES["completion_doc"]
        m.save()
        if m.due_date and day > m.due_date:
            messages.warning(request, f"तोकिएको मिति ({_bs(m.due_date)}) भन्दा {(day - m.due_date).days} दिन ढिला सम्पन्न।")
        messages.success(request, "सम्पन्न / जाँचपास दर्ता भयो। अब अन्तिम भुक्तानी गर्नुहोस्।")
        return None
    return ["अमान्य कार्य।"]


# ---------------------------------------------------------------- छाप्ने
@login_required
def minor_print(request, project_id, doc):
    if not has_perm(request.user, "minor.print"):
        return redirect("unauthorized")
    project = _project(request, project_id)
    m = mn.minor_of(project)
    ready = {"approval": bool(m and m.approved_at), "order": bool(m and m.order_date),
             "payment": mn.final_payment(m) is not None}
    if doc not in ready:
        return redirect("minor_detail", project.id)
    if not ready[doc]:
        messages.error(request, "यो कागजात छाप्ने चरण पुगेको छैन।")
        return redirect("minor_detail", project.id)
    MinorPrint.objects.create(minor=m, doc_type=doc, printed_by=request.user)

    from .procurement import METHODS

    fin = mn.final_payment(m)
    lab = {"agrim_tax": "अग्रिम आयकर / TDS", "vat": "भ्याट कट्टी", "dharauti": "धरौटी"}
    pays = list(m.payments.all())
    return render(request, "projects/minor_print.html", {
        "project": project, "m": m, "doc": doc, "method": m.method, "method_label": mn.METHOD_LABEL[m.method],
        "law": METHODS[m.method]["law"], "quotes": list(m.quotes.all()), "fin": fin, "pays": pays,
        "prev": [p for p in pays if p.kind != "final"], "prev_total": mn.paid(m, True),
        "fin_taxes": [(lab.get(k, k), mn.D(v)) for k, v in (fin.taxes.items() if fin else [])],
        "today": date.today(), "back": f"/Projects/Minor/{project.id}/",
    })
