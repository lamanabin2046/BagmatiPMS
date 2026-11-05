"""सार्वजनिक परीक्षण / सुनुवाइ र अनुगमन समितिको प्रतिवेदन."""
import os
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import has_perm

from .models import PublicAudit, PublicAuditFile
from .workflow import audit_is_required, bs_date

NP = str.maketrans("०१२३४५६७८९", "0123456789")
FILE_TYPES = (".pdf", ".jpg", ".jpeg", ".png", ".webp")
FILE_MAX_MB = 10


def _project(request, project_id):
    from .views_workflow import _scoped

    qs, _ = _scoped(request)
    return get_object_or_404(qs, id=project_id)


def _int(raw):
    try:
        return max(0, int((raw or "0").strip().translate(NP) or 0))
    except ValueError:
        return None


def _money(raw):
    raw = (raw or "").strip().translate(NP).replace(",", "")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return "bad"


def _date(raw):
    raw = (raw or "").strip().translate(NP)
    if not raw:
        return None
    from .views import convert_nepali_to_english

    return convert_nepali_to_english(raw) or "bad"


@login_required
def public_audit(request, project_id):
    project = _project(request, project_id)
    if not has_perm(request.user, "uc.public_audit"):
        return redirect("unauthorized")
    audit = getattr(project, "public_audit", None)

    if request.method == "POST" and request.POST.get("action") == "delete_file" and audit:
        f = get_object_or_404(PublicAuditFile, id=request.POST.get("file_id"), audit=audit)
        f.file.delete(save=False)
        f.delete()
        messages.success(request, "फाइल हटाइयो।")
        return redirect("uc_public_audit", project_id=project.id)

    if request.method == "POST":
        errors = []
        d = request.POST
        date, mdate = _date(d.get("date")), _date(d.get("monitoring_date"))
        total, women = _int(d.get("participants_total")), _int(d.get("participants_women"))
        income, expense = _money(d.get("income_presented")), _money(d.get("expense_presented"))
        if date in (None, "bad"):
            errors.append("सार्वजनिक परीक्षणको मिति मिलेन (YYYY-MM-DD)।")
        if mdate == "bad":
            errors.append("अनुगमन मिति मिलेन।")
        if total is None or women is None:
            errors.append("सहभागी संख्या अङ्कमा लेख्नुहोस्।")
        elif women > total:
            errors.append("महिला सहभागी कुल सहभागीभन्दा बढी हुन सक्दैन।")
        if "bad" in (income, expense):
            errors.append("आम्दानी / खर्च रकम मिलेन।")
        uploads = []
        for kind, _label in PublicAuditFile.KINDS:
            for f in request.FILES.getlist(f"files_{kind}"):
                ext = os.path.splitext(f.name)[1].lower()
                if ext not in FILE_TYPES:
                    errors.append(f"{f.name}: PDF वा फोटो मात्र।")
                elif f.size > FILE_MAX_MB * 1024 * 1024:
                    errors.append(f"{f.name}: {FILE_MAX_MB} MB भन्दा सानो हुनुपर्छ।")
                else:
                    uploads.append((kind, f))
        finding = d.get("monitoring_finding") if d.get("monitoring_finding") in dict(PublicAudit.FINDINGS) else ""
        if errors:
            for e in errors:
                messages.error(request, e)
            if uploads:
                messages.error(request, "फाइल फेरि छान्नुहोस् (browser ले छानेको फाइल सम्झँदैन)।")
        else:
            audit = audit or PublicAudit(project=project, created_by=request.user)
            audit.date, audit.monitoring_date = date, mdate
            audit.participants_total, audit.participants_women = total, women
            audit.income_presented, audit.expense_presented = income, expense
            audit.monitoring_finding = finding
            for f in ("venue", "chaired_by", "decision", "issues", "monitoring_members", "monitoring_remarks"):
                setattr(audit, f, (d.get(f) or "").strip())
            audit.save()
            for kind, f in uploads:
                PublicAuditFile.objects.create(audit=audit, kind=kind, file=f, uploaded_by=request.user)
            messages.success(request, f"“{project.name}” को सार्वजनिक परीक्षण विवरण सुरक्षित भयो।")
            return redirect("uc_public_audit", project_id=project.id)
        form = d
    else:
        form = None

    files = {}
    if audit:
        for f in audit.files.all():
            files.setdefault(f.kind, []).append(f)
    return render(request, "Admin/User/public_audit.html", {
        "project": project, "audit": audit, "form": form, "required": audit_is_required(),
        "kinds": [(k, l, files.get(k, [])) for k, l in PublicAuditFile.KINDS],
        "findings": PublicAudit.FINDINGS,
        "date_bs": bs_date(audit.date) if audit else "", "mdate_bs": bs_date(audit.monitoring_date) if audit else "",
        "committee": getattr(project, "user_committee", None),
        "estimate": getattr(project, "cost_estimate", None),
        "final": getattr(project, "final_payment", None),
    })


@login_required
def print_public_audit(request, project_id):
    project = _project(request, project_id)
    if not (has_perm(request.user, "uc.public_audit") or has_perm(request.user, "uc.payment_print")):
        return redirect("unauthorized")
    audit = get_object_or_404(PublicAudit, project=project)
    return render(request, "Admin/User/print_public_audit.html", {
        "project": project, "audit": audit, "usercommittee": getattr(project, "user_committee", None),
        "cost_estimate": getattr(project, "cost_estimate", None),
        "final_payment": getattr(project, "final_payment", None),
        "date_bs": bs_date(audit.date), "mdate_bs": bs_date(audit.monitoring_date),
        "installments": list(project.installments.all()),
    })
