"""किस्ता भुक्तानी (पेश्की / रनिङ बिल) — उपभोक्ता समिति योजनाका लागि, जति पनि किस्ता।

नियम: स्वीकृत (वा पुरानो सम्झौता छापिएको) भएपछि मात्र; अन्तिम भुक्तानी भएपछि थप्न नमिल्ने;
जम्मा किस्ता कार्यालयले बेहोर्ने रकम (लागत अनुमानको बजेट − कन्टिन्जेन्सी) भन्दा बढी हुन नहुने।
अन्तिम भुक्तानीमा यी किस्ता आफैँ कट्टी हुन्छन् (FinalPayment.net_payment)।
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.permissions import has_perm
from projects.models import Project

from .models import DocumentPrint, Installment
from .tax import active_heads, parse_tax_rows, tax_labels, tax_rows
from .workflow import AGREEMENT_DOCS, bs_date

NP = str.maketrans("०१२३४५६७८९", "0123456789")


def _money(raw):
    try:
        return Decimal((raw or "0").strip().translate(NP).replace(",", "") or "0")
    except InvalidOperation:
        return None


def office_share(project):
    est = getattr(project, "cost_estimate", None)
    if est is None:
        return Decimal("0")
    return (est.budget or 0) - (est.contingency_amount or 0)


def can_pay(project):
    """(बन्छ?, कारण)"""
    if getattr(project, "final_payment", None) is not None:
        return False, "अन्तिम भुक्तानी भइसकेकोले थप किस्ता दिन मिल्दैन।"
    approved = getattr(project, "uc_approval", None) is not None or project.document_prints.filter(
        doc_type__in=[d for d, _l, _u in AGREEMENT_DOCS]).exists()
    if not approved:
        return False, "सम्झौता (रुजु / स्वीकृत) भएपछि मात्र किस्ता दिन मिल्छ।"
    return True, ""


def _scoped_project(request, project_id):
    from .views_workflow import _scoped

    qs, _ = _scoped(request)
    return get_object_or_404(qs, id=project_id)


def _heads_for(tax_deduction):
    from types import SimpleNamespace

    heads = active_heads()
    have = {h.code for h in heads}
    labels = tax_labels()
    for code in tax_deduction or {}:
        if code not in have:
            heads.append(SimpleNamespace(code=code, name=labels.get(code, code)))
    return heads


@login_required
def installments(request, project_id, inst_id=None):
    """योजनाका किस्ता: सूची + थप्ने/सच्याउने फारम."""
    project = _scoped_project(request, project_id)
    if not (has_perm(request.user, "uc.valuation") or has_perm(request.user, "uc.payment_print")):
        return redirect("unauthorized")
    can_edit = has_perm(request.user, "uc.valuation")
    items = list(project.installments.all())
    editing = get_object_or_404(Installment, id=inst_id, project=project) if inst_id else None
    ok, why = can_pay(project)
    share = office_share(project)
    paid = sum((i.amount for i in items), Decimal("0"))

    if request.method == "POST" and can_edit:
        if request.POST.get("action") == "delete":
            last = items[-1] if items else None
            if last and str(last.id) == request.POST.get("id") and ok:
                last.delete()
                messages.success(request, f"{last.label} हटाइयो।")
            else:
                messages.error(request, "अन्तिम (पछिल्लो) किस्ता मात्र हटाउन मिल्छ।")
            return redirect("uc_installments", project_id=project.id)

        if not ok:
            messages.error(request, why)
            return redirect("uc_installments", project_id=project.id)
        errors = []
        kind = request.POST.get("kind") if request.POST.get("kind") in dict(Installment.KINDS) else "running"
        amount, work = _money(request.POST.get("amount")), _money(request.POST.get("work_value"))
        if amount is None or amount <= 0:
            errors.append("भुक्तानी रकम मिलेन।")
        if work is None or work < 0:
            errors.append("कामको मूल्याङ्कन रकम मिलेन।")
        allowed = {h.code for h in active_heads()} | set((editing.tax_deduction if editing else {}) or {})
        taxes, tax_errors = parse_tax_rows(request.POST, allowed)
        errors += tax_errors
        others = paid - (editing.amount if editing else 0)
        if amount and share and others + amount > share:
            errors.append(f"जम्मा किस्ता रु. {others + amount:,.2f} कार्यालयले बेहोर्ने रकम रु. {share:,.2f} भन्दा बढी भयो।")
        if amount:
            from projects.budget import check_payment
            if (e := check_payment(project, others + amount, "यो किस्ता")):
                errors.append(e)
        if amount and sum(Decimal(str(v)) for v in taxes.values()) > amount:
            errors.append("कर कट्टी भुक्तानी रकमभन्दा बढी भयो।")
        date_ad = None
        if request.POST.get("date"):
            from .views import convert_nepali_to_english

            date_ad = convert_nepali_to_english(request.POST["date"].strip().translate(NP))
            if not date_ad:
                errors.append("मिति मिलेन (YYYY-MM-DD)।")
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            inst = editing or Installment(project=project, number=(items[-1].number + 1) if items else 1,
                                          created_by=request.user)
            inst.kind, inst.amount, inst.work_value = kind, amount, work or 0
            inst.tax_deduction, inst.date = taxes, date_ad
            inst.remarks = (request.POST.get("remarks") or "").strip()
            inst.save()
            messages.success(request, f"{inst.label} सुरक्षित भयो। खुद भुक्तानी रु. {inst.net_amount:,.2f}")
            return redirect("uc_installments", project_id=project.id)
        form = request.POST
    else:
        form = None

    labels = tax_labels()
    rows = [{"i": i, "date_bs": bs_date(i.date),
             "taxes": [(labels.get(k, k), v) for k, v in (i.tax_deduction or {}).items()]} for i in items]
    tax_src = editing.tax_deduction if editing else {}
    return render(request, "Admin/User/installments.html", {
        "project": project, "rows": rows, "editing": editing, "form": form,
        "can_edit": can_edit, "can_pay": ok, "why": why,
        "share": share, "paid": paid, "remaining": share - paid,
        "next_number": (items[-1].number + 1) if items else 1,
        "kinds": Installment.KINDS,
        "editing_date_bs": bs_date(editing.date) if editing else "",
        "tax_heads": _heads_for(tax_src),
        "tax_rows": (list(zip(form.getlist("tax_head"), form.getlist("tax_amount"))) if form is not None else None)
                    or tax_rows(tax_src) or [(h.code, "") for h in active_heads()] or [("", "")],
        "can_add_tax_head": can_edit, "tax_base": "amount", "net_label": "खुद भुक्तानी (कर कट्टीपछि)",
        "committee": getattr(project, "user_committee", None),
    })


@login_required
def print_installment(request, inst_id):
    inst = get_object_or_404(Installment.objects.select_related("project"), id=inst_id)
    project = _scoped_project(request, inst.project_id)
    if not has_perm(request.user, "uc.payment_print"):
        messages.error(request, "यो कागजात छाप्ने अनुमति तपाईंलाई छैन।")
        return redirect("usercommittee_workflow")
    labels = tax_labels()
    previous = project.installments.filter(number__lt=inst.number)
    return render(request, "Admin/User/print_installment_tippani.html", {
        "inst": inst, "project": project, "usercommittee": getattr(project, "user_committee", None),
        "cost_estimate": getattr(project, "cost_estimate", None),
        "taxes": [(labels.get(k, k), v) for k, v in (inst.tax_deduction or {}).items()],
        "previous": previous, "previous_total": previous.aggregate(t=Sum("amount"))["t"] or 0,
        "share": office_share(project), "date_bs": bs_date(inst.date),
    })


@login_required
def bank_account(request, project_id):
    """सम्झौतापछि: बैंक खाता खोल्ने पत्रअनुसार समितिले खाता खोलेपछि खाता विवरण राख्ने (किस्ता/भुक्तानी टिप्पणीमा आउँछ)."""
    from accounts.permissions import user_perms

    from .views import apply_bank, convert_english_to_nepali

    project = _scoped_project(request, project_id)
    if not (user_perms(request.user) & {"uc.agreement_print", "uc.committee"}):
        return redirect("unauthorized")
    committee = getattr(project, "user_committee", None)
    if committee is None:
        messages.error(request, "उपभोक्ता समिति गठन भएको छैन।")
        return redirect("usercommittee_workflow")
    approved = getattr(project, "uc_approval", None) is not None or project.document_prints.filter(
        doc_type__in=[d for d, _l, _u in AGREEMENT_DOCS]).exists()
    if not approved:
        messages.error(request, "सम्झौता (रुजु / स्वीकृत) भएपछि मात्र बैंक खाता राख्न मिल्छ।")
        return redirect("usercommittee_workflow")

    if request.method == "POST":
        apply_bank(committee, request.POST)
        if committee.account_number and not committee.bank_name:
            messages.error(request, "बैंकको नाम पनि लेख्नुहोस्।")
            return render(request, "Admin/User/bank_account.html",
                          {"project": project, "committee": committee, "form": request.POST})
        committee.save(update_fields=["bank_name", "bank_branch", "account_number", "account_name",
                                      "account_opened_date"])
        messages.success(request, "बैंक खाता विवरण सुरक्षित भयो।" if committee.has_bank_account
                         else "बैंक खाता विवरण हटाइयो।")
        from django.utils.http import url_has_allowed_host_and_scheme
        nxt = request.POST.get("next") or ""
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            return redirect(nxt)
        return redirect("usercommittee_workflow")

    return render(request, "Admin/User/bank_account.html", {
        "project": project, "committee": committee, "uc": committee,
        "bank_opened_bs": convert_english_to_nepali(committee.account_opened_date) if committee.account_opened_date else "",
        "next": request.GET.get("next", ""),
    })
