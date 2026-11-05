from django.shortcuts import render,redirect,get_object_or_404
from django.contrib import messages
from .models import FiscalYear, Procurement_Type, Project_Type, Budget_Type, Ward, Project, ProjectTimeline

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.core.exceptions import ObjectDoesNotExist
from decimal import Decimal
import unicodedata
import re

# Create your views here.

def devanagari_to_english_number(dev_num_str):
    devanagari_digits = '०१२३४५६७८९'
    english_digits = '0123456789'
    translation_table = str.maketrans(devanagari_digits, english_digits)
    return dev_num_str.translate(translation_table)




def _sector_pair(post):
    """फारमबाट (क्षेत्र, उपक्षेत्र) — उपक्षेत्र छानिएको क्षेत्रकै हुनुपर्छ।"""
    from .models import Sector, SubSector

    sector = Sector.objects.filter(id=post.get("sector") or 0).first() if str(post.get("sector", "")).isdigit() else None
    sub = SubSector.objects.filter(id=post.get("subsector") or 0).first() if str(post.get("subsector", "")).isdigit() else None
    if sub is not None and sector is None:
        sector = sub.sector
    if sub is not None and sub.sector_id != sector.id:
        sub = None
    return sector, sub


def _sector_ctx(project=None):
    from .models import Sector

    sectors = list(Sector.objects.filter(is_active=True).prefetch_related("subsectors"))
    # सम्पादनमा: निष्क्रिय भए पनि हालको क्षेत्र/उपक्षेत्र देखिनुपर्छ
    if project is not None and project.sector_id and all(x.id != project.sector_id for x in sectors):
        sectors.append(project.sector)
    return {"sectors": sectors}


def _budget_head(post):
    from .models import BudgetHead

    v = str(post.get("budget_head", "") or "")
    return BudgetHead.objects.filter(id=v).first() if v.isdigit() else None


def _budget_errors(request, project, budget, head, fiscalyear_id):
    from .budget import check_project_budget

    try:
        amount = Decimal(str(budget or "0").replace(",", "").strip() or "0")
    except Exception:
        messages.error(request, "विनियोजित बजेट रकम अङ्कमा लेख्नुहोस्।")
        return True
    errors = check_project_budget(project, amount, head, fiscalyear_id)
    for e in errors:
        messages.error(request, e)
    return bool(errors)


def add_project(request):

    
    from .fiscal import current_fy

    cur = current_fy()
    if request.method == "POST":
        fiscal_id = request.POST.get("fiscal")
        if cur is None or str(fiscal_id) != str(cur.id):   # नयाँ योजना चालु आ.व. मा मात्र
            messages.error(request, f"नयाँ योजना चालु आ.व. ({cur.name if cur else '—'}) मा मात्र दर्ता गर्न मिल्छ।")
            return redirect('add_project')
        fiscalYear = FiscalYear.objects.get(id =fiscal_id )
        # खरिद विधि दर्तामा होइन — वार्षिक खरिद योजनाबाट (projects/views_app.py)
        procurement_type = None
        project_type_id = request.POST.get("project_type")
        project_type = Project_Type.objects.get(id =project_type_id )
        budget_type_id = request.POST.get("budget_type")
        budget_type = Budget_Type.objects.get(id =budget_type_id )
        ward_id = request.POST.get("ward")
        ward = Ward.objects.get(id=ward_id)
        name = request.POST.get("name")
        address = request.POST.get("address")
        budget = request.POST.get("budget")
                # ✅ Convert Devanagari to English number
        if budget:
            budget = devanagari_to_english_number(budget)
       
        sector, subsector = _sector_pair(request.POST)
        head = _budget_head(request.POST)
        if _budget_errors(request, None, budget, head, fiscal_id):
            return redirect('add_project')
        project = Project (
            budget_head = head,
            sector = sector,
            subsector = subsector,
            fiscalyear = fiscalYear,
            name = name,
            ward = ward,
            project_type = project_type,
            address = address,
            procurement_type = procurement_type,
            budget_type =budget_type,
            budget = budget,
            execution_mode = request.POST.get("execution_mode", "") if request.POST.get("execution_mode", "") in ("", "municipal", "ward") else "",
        )
        project.save()
        messages.success(request, "योजना दर्ता भयो। अब वार्षिक खरिद योजनाबाट खरिद विधि तोक्नुहोस्।")
        return redirect('view_projects') 

    
    fiscalyear = [cur] if cur else FiscalYear.objects.all()   # नयाँ योजना: चालु आ.व. मात्र
    ward = Ward.objects.all()
    procurement_type = Procurement_Type.objects.all()
    budget_type = Budget_Type.objects.all()
    project_type = Project_Type.objects.all()
    
    context = {
        "fiscalyear":fiscalyear,
        "ward":ward,
        "procurement_type":procurement_type,
        "budget_type":budget_type,
        "project_type":project_type,
        **_sector_ctx(),
    }
    
    return render(request,"Admin/User/add_projects.html",context)




IMPORT_REQUIRED_COLUMNS = [
    "name",
    "address",
    "budget",
    "budget_type_id",
    "fiscalyear_id",
    "ward_id",
    "project_type_id",
]


# ऐच्छिक: क्षेत्र / उपक्षेत्र नामबाट (सेटिङ → क्षेत्र / उपक्षेत्रमा भएको नाम जस्ताको तस्तै)
IMPORT_OPTIONAL_COLUMNS = ["sector", "subsector", "budget_head", "procurement_type_id", "status"]


def _to_id(value):
    """ढाँचाको ड्रपडाउन मान "5 | वडा ३" → 5 (सादा अङ्क पनि चल्छ)।"""
    if isinstance(value, str) and "|" in value:
        value = value.split("|", 1)[0]
    return int(_to_number(value))


def _norm_name(text):
    """तुलनाका लागि: नेपाली अङ्क → अङ्ग्रेजी, "वडा"/"नं." हटाउने, खाली ठाउँ मिलाउने।"""
    t = devanagari_to_english_number(str(text or "")).strip()
    t = re.sub(r"^(वडा\s*(नं\.?)?\s*)", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _resolve(model, value, attr="name", label=""):
    """Excel को मान → रेकर्ड।
    "id | नाम": पहिले नामबाट (अर्को पालिकाको फाइल पनि चल्ने), नभेटिए id बाट।
    सादा मान: वडामा पहिले नाम (वडाको नाम नै अङ्क), अरूमा अङ्क भए id (पुरानो ढाँचा), पाठ भए नाम।"""
    import pandas as pd

    if value is None or (not isinstance(value, str) and pd.isna(value)) or not str(value).strip():
        raise ValueError(f"{label or attr} खाली छ")
    s = str(value).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    left, name = (x.strip() for x in s.split("|", 1)) if "|" in s else ("", s)

    def by_name():
        want = _norm_name(name)
        return next((o for o in model.objects.all() if _norm_name(getattr(o, attr)) == want), None)

    def by_id(v):
        v = devanagari_to_english_number(v)
        return model.objects.filter(id=int(v)).first() if v.isdigit() else None

    if left:
        obj = by_name() or by_id(left)
    elif model is Ward:
        obj = by_name() or by_id(name)
    else:
        obj = by_id(name) if devanagari_to_english_number(name).isdigit() else by_name()
    if obj is None:
        raise ValueError(f"{label or attr} “{s}” भेटिएन")
    return obj


def import_template(request):
    """योजना आयातको Excel ढाँचा — यही पालिकाको चालु आ.व., वडा, बजेट प्रकार, योजना प्रकार, क्षेत्रका ड्रपडाउन सहित।"""
    from django.http import HttpResponse

    from .import_template import build

    tenant = getattr(request, "tenant", None)
    data, fy_name = build(getattr(tenant, "full_name", "") or "", sample=True)
    resp = HttpResponse(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    fname = f"project_import_template_{fy_name.replace('/', '-') or 'fy'}.xlsx"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


def _import_sector(row):
    """(Sector, SubSector) Excel पङ्क्तिबाट; नाम नमिले ValueError."""
    import pandas as pd

    from .models import Sector, SubSector

    def val(key):
        v = row.get(key) if hasattr(row, "get") else None
        return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()

    sec_name, sub_name = val("sector"), val("subsector")
    sector = sub = None
    if sec_name:
        sector = Sector.objects.filter(name=sec_name).first()
        if sector is None:
            raise ValueError(f"क्षेत्र “{sec_name}” भेटिएन")
    if sub_name:
        qs = SubSector.objects.filter(name=sub_name)
        if sector is not None:
            qs = qs.filter(sector=sector)
        sub = qs.first()
        if sub is None:
            raise ValueError(f"उपक्षेत्र “{sub_name}” भेटिएन" + (f" (“{sector.name}” भित्र)" if sector else ""))
        sector = sector or sub.sector
    return sector, sub


def _import_ptype(row):
    """ऐच्छिक (पुरानो ढाँचा): खरिद विधि id — नभए खाली, वार्षिक खरिद योजनाबाट तोकिन्छ।"""
    import pandas as pd

    v = row.get("procurement_type_id") if hasattr(row, "get") else None
    if v is None or (not isinstance(v, str) and pd.isna(v)) or not str(v).strip():
        return None
    return Procurement_Type.objects.get(id=int(_to_number(v)))


def _import_head(row, fiscalyear):
    """बजेट शीर्षक — उपशीर्षक नं. वा नाम (त्यही आ.व.को); नमिले ValueError."""
    import pandas as pd

    from .models import BudgetHead

    v = row.get("budget_head") if hasattr(row, "get") else None
    text = "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text:
        return None
    qs = BudgetHead.objects.filter(fiscalyear=fiscalyear)
    head = qs.filter(code=text).first() or qs.filter(name=text).first()
    if head is None:
        raise ValueError(f"बजेट शीर्षक “{text}” {fiscalyear.name} मा भेटिएन")
    return head


def _normalize_header(value):
    """'  Ward ID ' -> 'ward_id'. Makes header matching forgiving about
    case, surrounding spaces, inner spaces/hyphens and invisible BOM/NBSP
    characters that Excel sometimes carries in."""
    text = unicodedata.normalize("NFKC", str(value)).replace("\ufeff", "")
    text = text.strip().lower()
    return re.sub(r"[\s\-]+", "_", text)


def _find_project_table(sheets):
    """Return (dataframe, sheet_name) for the first sheet that has all the
    required headers in one of its first 10 rows. Prefers a sheet named
    'Projects'. Returns (None, first_row_headers_seen) if nothing matched."""
    import pandas as pd

    names = list(sheets.keys())
    names.sort(key=lambda n: 0 if str(n).strip().lower() == "projects" else 1)
    first_seen = []
    for sheet_name in names:
        raw = sheets[sheet_name]
        for header_row in range(min(10, len(raw))):
            headers = [_normalize_header(v) if not pd.isna(v) else "" for v in raw.iloc[header_row]]
            if not first_seen and any(headers):
                first_seen = [h for h in headers if h]
            if all(col in headers for col in IMPORT_REQUIRED_COLUMNS):
                df = raw.iloc[header_row + 1:].copy()
                df.columns = headers
                df = df.dropna(how="all")          # ignore blank rows
                # keep original Excel row numbers for error messages
                df.index = df.index + 1
                return df, sheet_name
    return None, first_seen


def _to_number(value):
    """Accepts 2500000, '2,500,000', '२५,००,०००'. Raises ValueError on blanks."""
    import pandas as pd

    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError("empty value")
    text = devanagari_to_english_number(str(value)).replace(",", "").strip()
    if text == "":
        raise ValueError("empty value")
    return float(text)


def import_excel(request):
    if request.method != "POST" or "excel_file" not in request.FILES:
        if request.method == "POST":
            messages.error(request, "Please upload an Excel file.")
        return render(request, "Admin/User/import_excel.html")

    # pandas/numpy is imported here (not at module level) on purpose: it
    # pulls in OpenBLAS, which spins up dozens of native threads on first
    # import. Loading it lazily, only for this Excel-import view, keeps
    # every other page light on the process-limited shared host.
    import pandas as pd

    try:
        # Read every sheet with no header assumption; we locate the header
        # row ourselves so a title row or sheet order doesn't break imports.
        sheets = pd.read_excel(request.FILES["excel_file"], sheet_name=None, header=None, dtype=object)
        df, info = _find_project_table(sheets)

        if df is None:
            messages.error(
                request,
                "Could not find the header row. Required columns: "
                + ", ".join(IMPORT_REQUIRED_COLUMNS)
                + ". Columns found in your file: "
                + (", ".join(info) if info else "(none)"),
            )
            return render(request, "Admin/User/import_excel.html")

        success = 0
        failed = 0
        sample_rows = 0

        for excel_row, row in df.iterrows():
            try:
                name = row["name"]
                address = row["address"]
                blank = lambda v: v is None or (not isinstance(v, str) and pd.isna(v)) or not str(v).strip()  # noqa: E731
                if blank(name) and blank(address) and blank(row.get("budget")):
                    continue        # ड्रपडाउन मात्र छानिएको खाली पङ्क्ति
                if not blank(name) and str(name).strip().startswith("नमुना:"):
                    sample_rows += 1
                    continue        # ढाँचाको नमुना पङ्क्ति
                if pd.isna(name) or not str(name).strip():
                    raise ValueError("name is empty")
                if pd.isna(address) or not str(address).strip():
                    raise ValueError("address is empty")
                sector, subsector = _import_sector(row)
                fy = _resolve(FiscalYear, row["fiscalyear_id"], "name", "आर्थिक वर्ष")
                from .fiscal import current_fy_id

                if fy.id != current_fy_id():
                    raise ValueError(f"आ.व. {fy.name} चालु आ.व. होइन — नयाँ योजना चालु आ.व. मा मात्र")
                head = _import_head(row, fy)
                amount = _to_number(row["budget"])
                if head is not None:
                    from .budget import check_project_budget
                    errs = check_project_budget(None, amount, head, fy.id)
                    if errs:
                        raise ValueError(errs[0])

                Project.objects.create(
                    budget_head=head,
                    name=str(name).strip(),
                    address=str(address).strip(),
                    budget=_to_number(row["budget"]),
                    status=int(_to_number(row["status"])) if not blank(row.get("status")) else 0,
                    fiscalyear=fy,
                    budget_type=_resolve(Budget_Type, row["budget_type_id"], "name", "बजेट व्यहोर्ने स्रोत"),
                    procurement_type=_import_ptype(row),
                    ward=_resolve(Ward, row["ward_id"], "name", "वडा"),
                    project_type=_resolve(Project_Type, row["project_type_id"], "type", "योजनाको प्रकार"),
                    sector=sector,
                    subsector=subsector,
                )
                success += 1

            except ObjectDoesNotExist as e:
                failed += 1
                messages.error(request, f"Row {excel_row}: invalid ID — {e}")
            except Exception as e:
                failed += 1
                messages.error(request, f"Row {excel_row}: {e}")

        if not success and not failed and sample_rows:
            messages.warning(request, "नमुना पङ्क्ति मात्र भेटियो — ५ औँ पङ्क्तिदेखि आफ्ना योजना भरेर फेरि अपलोड गर्नुहोस्।")
        elif failed:
            messages.warning(request, f"Import finished: {success} projects added, {failed} rows skipped (see errors).")
        else:
            messages.success(request, f"Import completed successfully. {success} projects added.")

    except Exception as e:
        messages.error(request, f"Import failed: {str(e)}")

    return render(request, "Admin/User/import_excel.html")






def view_projects(request):
    from .fiscal import current_fy

    latest_fiscal_year = current_fy()   # पूर्वनिर्धारित: चालु आ.व.

    # ================= खोज / फिल्टर (site-wide search) =================
    q = (request.GET.get("q") or "").strip()
    ward_id = request.GET.get("ward") or ""
    fiscalyear_id = request.GET.get("fiscalyear") or ""
    procurement_type_id = request.GET.get("procurement_type") or ""
    budget_type_id = request.GET.get("budget_type") or ""

    filters_applied = bool(q or ward_id or fiscalyear_id or procurement_type_id or budget_type_id)

    projects = Project.objects.select_related(
        "ward", "sector", "subsector", "fiscalyear", "project_type", "procurement_type", "budget_type", "user_committee"
    )

    if fiscalyear_id:
        projects = projects.filter(fiscalyear_id=fiscalyear_id)
    elif not filters_applied:
        # कुनै फिल्टर नलगाईं पृष्ठ पहिलोपटक खोल्दा, पहिलेकै व्यवहार अनुसार
        # पछिल्लो आ.व.का योजनाहरू मात्र देखाउने।
        projects = projects.filter(fiscalyear=latest_fiscal_year)

    if q:
        projects = projects.filter(
            Q(name__icontains=q)
            | Q(user_committee__name__icontains=q)
            | Q(user_committee__chairman_name__icontains=q)
        ).distinct()

    if ward_id:
        projects = projects.filter(ward_id=ward_id)
    if procurement_type_id:
        projects = projects.filter(procurement_type_id=procurement_type_id)
    if budget_type_id:
        projects = projects.filter(budget_type_id=budget_type_id)

    projects = projects.order_by(
        'ward__id',   # Ward 1, 2, 3...
        '-id'         # Newest project first
    )

    context = {
        "projects": projects,
        "latest_fiscal_year": latest_fiscal_year,
        "filters_applied": filters_applied,

        # फिल्टर ड्रपडाउनका लागि विकल्पहरू
        "wards": Ward.objects.all(),
        "fiscalyears": FiscalYear.objects.all().order_by('-name'),
        "procurement_types": Procurement_Type.objects.all(),
        "budget_types": Budget_Type.objects.all(),

        # हाल छानिएका फिल्टर मानहरू (फारममा फिर्ता देखाउन)
        "selected_q": q,
        "selected_ward": ward_id,
        "selected_fiscalyear": fiscalyear_id,
        "selected_procurement_type": procurement_type_id,
        "selected_budget_type": budget_type_id,
    }

    return render(request, "Admin/User/view_projects.html", context)




def edit_project(request, id):
    project = Project.objects.get(id = id)
    fiscalyear = [project.fiscalyear] if project.fiscalyear_id else FiscalYear.objects.all()   # आ.व. बदल्न मिल्दैन (आ.व. बन्दले सार्छ)
    wards = Ward.objects.all()
    procurement_type = Procurement_Type.objects.all()
    budget_type = Budget_Type.objects.all()
    project_type = Project_Type.objects.all()
    
    
    context = {
        "project":project,
        "fiscalyear":fiscalyear,
        "wards":wards,
        "procurement_type":procurement_type,
        "budget_type":budget_type,
        "project_type":project_type,
        **_sector_ctx(project),
    }
    return render(request,"Admin/User/edit_project.html",context)



def update_project(request):
    if request.method == "POST":
        fiscal_year_id = request.POST.get('fiscal')
        project_id = request.POST.get('project_id')
        project_name = request.POST.get('name')
        ward_id = request.POST.get('ward_id')
        address = request.POST.get('address')
        budget = request.POST.get('budget')

        if budget:
            budget = devanagari_to_english_number(budget)
        fiscalyear = FiscalYear.objects.get(id=fiscal_year_id)
        budget_type_id = request.POST.get("budget_type")
        budget_type = Budget_Type.objects.get(id =budget_type_id )
        project_type_id = request.POST.get("project_type")
        project_type = Project_Type.objects.get(id = project_type_id)
        ward_id = request.POST.get("ward_id")
        ward = Ward.objects.get(id=ward_id)
        project = Project.objects.get(id=project_id)
        # बजेट शीर्षक फारममा छैन — पहिले तोकिएको भए त्यही राख्ने (Excel आयातबाट आएको)
        head = _budget_head(request.POST) if "budget_head" in request.POST else project.budget_head
        if _budget_errors(request, project, budget, head, fiscal_year_id):
            return redirect('edit_project', id=project.id)
        project.budget_head = head
        project.name = project_name   # खरिद विधि: वार्षिक खरिद योजनाबाट मात्र
        project.address = address
        project.budget = budget
        project.budget_type = budget_type
        if not project.fiscalyear_id:          # आ.व. यहाँबाट बदलिँदैन — आ.व. बन्दले मात्र (बहुवर्षीय) सार्छ
            project.fiscalyear = fiscalyear
        project.project_type = project_type
        project.ward = ward
        project.sector, project.subsector = _sector_pair(request.POST)
        mode = request.POST.get("execution_mode", project.execution_mode)
        if mode in ("", "municipal", "ward"):
            project.execution_mode = mode
        project.save()
        messages.success(request, 'Records are successfully updated')
        return redirect('view_projects')
    
    
    return render(request, 'Admin/User/edit_project.html')






def delete_project(request, pk):
    if request.method == "POST":
        project = get_object_or_404(Project, pk=pk)
        project.delete()
        messages.success(request, "Project deleted successfully.")
    return redirect('view_projects')  # change to your list view name




from django.contrib.auth.decorators import login_required

@login_required
def project_timeline(request, project_id):
    project = get_object_or_404(Project, id=project_id)

    timelines = ProjectTimeline.objects.filter(project=project).order_by('-created_at')
    # ordering already handled by Meta

    # Only ENGINEER and ADMIN can upload
    can_upload = request.user.user_type in ['1', '4']
    # 1 = ADMIN, 4 = ENGINEER

    if request.method == "POST" and can_upload:
        image = request.FILES.get("image")
        description = request.POST.get("description")
        stage_raw = request.POST.get("stage")
        stage = None
        if stage_raw:
            try:
                candidate = int(stage_raw)
                if candidate in dict(ProjectTimeline.STAGE_CHOICES):
                    stage = candidate
            except (TypeError, ValueError):
                stage = None

        if image and description:
            ProjectTimeline.objects.create(
                project=project,
                image=image,
                description=description,
                stage=stage,
                uploaded_by=request.user
            )
            return redirect("project_timeline", project_id=project.id)

    # =========================================================
    # FULL PROJECT OVERVIEW — cost estimate, user committee,
    # bidding/contract, advance payments, final valuation
    # =========================================================
    from biddings.models import SealedBid  # local import avoids app-loading order issues

    cost_estimate = getattr(project, "cost_estimate", None)
    user_committee = getattr(project, "user_committee", None)
    final_valuation = getattr(project, "final_payment", None)  # usercommittee.FinalPayment

    bids = (
        SealedBid.objects
        .filter(project=project)
        .select_related("contract", "contract__bond_issued")
        .prefetch_related(
            "contract__advance_payments__bank_guarantee",
            "contract__running_evaluations",
        )
        .order_by("-created_at")
    )

    advance_payments = []
    running_evaluations = []
    for bid in bids:
        contract = getattr(bid, "contract", None)
        if not contract:
            continue
        advance_payments.extend(contract.advance_payments.all())
        running_evaluations.extend(contract.running_evaluations.all())

    total_advance_paid = sum(
        (ap.approved_amount for ap in advance_payments), Decimal("0")
    )
    total_running_paid = sum(
        (rev.payable_amount for rev in running_evaluations), Decimal("0")
    )

    context = {
        "project": project,
        "timelines": timelines,
        "can_upload": can_upload,
        "stage_choices": ProjectTimeline.STAGE_CHOICES,

        "cost_estimate": cost_estimate,
        "user_committee": user_committee,
        "final_valuation": final_valuation,

        "bids": bids,
        "advance_payments": advance_payments,
        "total_advance_paid": total_advance_paid,
        "running_evaluations": running_evaluations,
        "total_running_paid": total_running_paid,
    }

    return render(request, "Admin/User/project_timeline.html", context)


# ======================================================================
# सेटिङ — लुकअप व्यवस्थापन (आर्थिक वर्ष / बजेट प्रकार / खरिद प्रकार)
# ======================================================================
# सबै तीनवटा मोडेल (FiscalYear, Budget_Type, Procurement_Type) मा साधारण
# `name` फिल्ड मात्र छ, र Project मोडेलका सम्बन्धित ForeignKey हरू
# on_delete=models.CASCADE भएकोले, प्रयोगमा रहेको लुकअप मेटाउँदा योजना नै
# मेटिने जोखिम हुन्छ। त्यसैले मेटाउनु अघि सधैं प्रयोग जाँच गरिन्छ।

def _is_admin(request):
    return request.user.is_authenticated and getattr(request.user, "user_type", None) == '1'


def _lookup_list_and_create(request, model, list_url_name, edit_url_name, delete_url_name, page_title, label, placeholder, fk_field_name):
    if not _is_admin(request):
        return redirect("unauthorized")

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, f"{label} लेख्नुहोस्।")
        elif model.objects.filter(name__iexact=name).exists():
            messages.error(request, f"यो {label} पहिले नै थपिएको छ।")
        else:
            model.objects.create(name=name)
            messages.success(request, f"{label} सफलतापूर्वक थपियो ✅")
        return redirect(list_url_name)

    items = model.objects.annotate(usage_count=Count(fk_field_name)).order_by("-id")

    context = {
        "page_title": page_title,
        "label": label,
        "placeholder": placeholder,
        "items": items,
        "edit_url_name": edit_url_name,
        "delete_url_name": delete_url_name,
        "fy_mode": model is FiscalYear,
    }
    return render(request, "Admin/Settings/manage_lookup.html", context)


def _lookup_edit(request, model, id, list_url_name, page_title, label):
    if not _is_admin(request):
        return redirect("unauthorized")

    item = get_object_or_404(model, id=id)

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, f"{label} लेख्नुहोस्।")
            return redirect(request.path)
        if model.objects.filter(name__iexact=name).exclude(id=item.id).exists():
            messages.error(request, f"यो {label} पहिले नै अर्को नामको रुपमा थपिएको छ।")
            return redirect(request.path)
        item.name = name
        item.save()
        messages.success(request, f"{label} सफलतापूर्वक सम्पादन गरियो ✅")
        return redirect(list_url_name)

    context = {
        "page_title": page_title,
        "label": label,
        "item": item,
        "list_url_name": list_url_name,
    }
    return render(request, "Admin/Settings/edit_lookup.html", context)


def _lookup_delete(request, model, id, list_url_name, label, fk_field_name):
    if not _is_admin(request):
        return redirect("unauthorized")

    item = get_object_or_404(model, id=id)

    if request.method == "POST":
        in_use = Project.objects.filter(**{f"{fk_field_name}_id": item.id}).exists()
        if in_use:
            messages.error(request, f"यो {label} कुनै योजनामा प्रयोग भइरहेको छ, त्यसैले मेटाउन मिल्दैन।")
        else:
            item.delete()
            messages.success(request, f"{label} सफलतापूर्वक हटाइयो ✅")

    return redirect(list_url_name)


# ----------------- आर्थिक वर्ष (FiscalYear) -----------------

def manage_fiscal_years(request):
    if request.method == "POST" and request.POST.get("action") == "set_current":
        if not _is_admin(request):
            return redirect("unauthorized")
        fy = get_object_or_404(FiscalYear, id=request.POST.get("id"))
        if fy.closed_at:
            messages.error(request, f"आ.व. {fy.name} बन्द भइसकेको छ — चालु बनाउन पहिले आ.व. बन्दबाट खोल्नुहोस्।")
        else:
            from .fiscal import set_current

            set_current(fy)
            messages.success(request, f"आ.व. {fy.name} अब चालु आ.व. हो — कामकाज यही आ.व. का योजनामा हुनेछ।")
        return redirect("manage_fiscal_years")
    return _lookup_list_and_create(
        request, FiscalYear,
        "manage_fiscal_years", "edit_fiscal_year", "delete_fiscal_year",
        "आर्थिक वर्ष व्यवस्थापन", "आर्थिक वर्ष", "जस्तै: २०८२/०८३",
        "project",
    )


def edit_fiscal_year(request, id):
    return _lookup_edit(request, FiscalYear, id, "manage_fiscal_years", "आर्थिक वर्ष सम्पादन", "आर्थिक वर्ष")


def delete_fiscal_year(request, id):
    return _lookup_delete(request, FiscalYear, id, "manage_fiscal_years", "आर्थिक वर्ष", "fiscalyear")


# ----------------- बजेट प्रकार (Budget_Type) -----------------

def manage_budget_types(request):
    return _lookup_list_and_create(
        request, Budget_Type,
        "manage_budget_types", "edit_budget_type", "delete_budget_type",
        "बजेट प्रकार व्यवस्थापन", "बजेट प्रकार", "जस्तै: पुँजीगत / चालु",
        "project",
    )


def edit_budget_type(request, id):
    return _lookup_edit(request, Budget_Type, id, "manage_budget_types", "बजेट प्रकार सम्पादन", "बजेट प्रकार")


def delete_budget_type(request, id):
    return _lookup_delete(request, Budget_Type, id, "manage_budget_types", "बजेट प्रकार", "budget_type")


# ----------------- खरिद प्रकार (Procurement_Type) -----------------

def manage_procurement_types(request):
    return _lookup_list_and_create(
        request, Procurement_Type,
        "manage_procurement_types", "edit_procurement_type", "delete_procurement_type",
        "खरिद प्रकार व्यवस्थापन", "खरिद प्रकार", "जस्तै: उपभोक्ता समिति मार्फत",
        "project",
    )


def edit_procurement_type(request, id):
    return _lookup_edit(request, Procurement_Type, id, "manage_procurement_types", "खरिद प्रकार सम्पादन", "खरिद प्रकार")


def delete_procurement_type(request, id):
    pt = get_object_or_404(Procurement_Type, id=id)
    if request.method == "POST" and pt.code:
        messages.error(request, f"“{pt.name}” कानुनी खरिद विधि हो (वार्षिक खरिद योजनामा प्रयोग हुने) — मेटाउन मिल्दैन, नाम मात्र बदल्न सकिन्छ।")
        return redirect("manage_procurement_types")
    return _lookup_delete(request, Procurement_Type, id, "manage_procurement_types", "खरिद प्रकार", "procurement_type")