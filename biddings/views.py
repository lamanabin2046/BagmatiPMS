# imports
# ==========================
from decimal import Decimal
import datetime
import traceback

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse

from nepali.date_converter import converter

from .models import *
from projects.models import Project




def devanagari_to_english_number(dev_num_str):
    devanagari_digits = '०१२३४५६७८९'
    english_digits = '0123456789'
    translation_table = str.maketrans(devanagari_digits, english_digits)
    return dev_num_str.translate(translation_table)


# def convert_nepali_to_english(nepali_date_str):
#     if nepali_date_str:
#         try:
#             nepali_year, nepali_month, nepali_day = map(int, nepali_date_str.split('-'))
#             english_year, english_month, english_day = converter.nepali_to_english(nepali_year, nepali_month, nepali_day)
#             return f"{english_year}-{english_month:02d}-{english_day:02d}"
#         except ValueError:
#             return None
#     return None

# def convert_english_to_nepali(english_date):
#     if english_date and english_date != 'None':
#         try:
#             # If it's a date object, convert to string 'YYYY-MM-DD'
#             if not isinstance(english_date, str):
#                 english_date = english_date.strftime('%Y-%m-%d')
                
#             english_year, english_month, english_day = map(int, english_date.split('-'))
#             nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
#             return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
#         except ValueError:
#             return None
#     return None

# ==============================
# Nepali (str) → English (date)
# ==============================
def convert_nepali_to_english(nepali_date_str):
    if not nepali_date_str:
        return None
    try:
        y, m, d = map(int, nepali_date_str.split("-"))
        ey, em, ed = converter.nepali_to_english(y, m, d)
        return datetime.date(ey, em, ed)   # ✅ date object
    except Exception:
        return None


# ==============================
# English (date) → Nepali (str)
# ==============================
def convert_english_to_nepali(english_date):
    if not english_date:
        return None
    try:
        if isinstance(english_date, str):
            y, m, d = map(int, english_date.split("-"))
        else:
            y, m, d = english_date.year, english_date.month, english_date.day

        ny, nm, nd = converter.english_to_nepali(y, m, d)
        return f"{ny}-{nm:02d}-{nd:02d}"
    except Exception:
        return None




def ADD_BID_DETAIL(request):

    # ================= POST =================
    if request.method == "POST":
        project_id = request.POST.get("project_id")

        if not project_id:
            messages.error(request, "Project is required.")
            return redirect("add_bid_detail")

        project = get_object_or_404(Project, id=project_id)

        # ❌ Prevent duplicate bidding
        if SealedBid.objects.filter(project=project).exists():
            messages.error(request, "This Bidding already exists!")
            return redirect("add_bid_detail")

        # ---------------- RAW INPUTS ----------------
        budget = request.POST.get("budget")
        contingency_amount = request.POST.get("congtingency")
        ps_amount = request.POST.get("ps_amount")
        cost_estimate_vat = request.POST.get("estimate_with_vat")
        total_cost_estimate = request.POST.get("totalcost")
        bidding_number = request.POST.get("bidding_number")
        bidding_amount = request.POST.get("bidding_amount")

        bidder_name_nepali = request.POST.get("bidder_name_nepali")
        bidder_owner_nepali = request.POST.get("bidder_owner_nepali")
        bidder_address_nepali = request.POST.get("bidder_address_nepali")

        bid_published_date_np = request.POST.get("bid_published_date")
        bid_opening_date_np = request.POST.get("bid_opening_date")
        bid_evaluation_date_np = request.POST.get("bid_evaluation_date")

        # ---------------- DATE CONVERTER ----------------
        def nepali_to_english(nepali_date):
            if nepali_date:
                y, m, d = map(int, nepali_date.split("-"))
                ey, em, ed = converter.nepali_to_english(y, m, d)
                return f"{ey}-{em:02d}-{ed:02d}"
            return None

        bid_published_date = nepali_to_english(bid_published_date_np)
        bid_opening_date = nepali_to_english(bid_opening_date_np)
        bid_evaluation_date = nepali_to_english(bid_evaluation_date_np)

        # ---------------- SAVE ----------------
        bidding = SealedBid.objects.create(
            project=project,
            budget=Decimal(budget),
            contingency_amount=Decimal(contingency_amount),
            ps_amount=Decimal(ps_amount),
            cost_estimate_vat=Decimal(cost_estimate_vat),
            total_cost_estimate=Decimal(total_cost_estimate),
            bidding_number=bidding_number,
            bidding_amount=Decimal(bidding_amount),

            bid_published_date=bid_published_date,
            bid_opening_date=bid_opening_date,
            bid_evaluation_date=bid_evaluation_date,

            bidder_name_nepali=bidder_name_nepali,
            bidder_owner_nepali=bidder_owner_nepali,
            bidder_address_nepali=bidder_address_nepali,

            status=0  # Published
        )

        # Update project status
        project.status = 1
        project.save()

        messages.success(request, "Bidding record saved successfully!")
        return redirect("print_asay_notice", id=bidding.id)

    # ================= GET =================
    projects = Project.objects.filter(procurement_type=2, status=0)

    return render(
        request,
        "Admin/Bidding/add_bidding.html",
        {"projects": projects},
    )




def print_asay_notice(request, id):
    bidding = SealedBid.objects.get(id = id)
    evaluation_date_english = bidding.bid_evaluation_date
    
    
    def convert_english_to_nepali(english_date_str):
        if english_date_str:
            english_year, english_month, english_day = map(int, english_date_str.split('-'))
            nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
            return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
        return None

    # Convert the start date from English to Nepali
    evaluation_date = convert_english_to_nepali(str(evaluation_date_english))

    
    
    context = {
        "bidding":bidding,
        "evaluation_date":evaluation_date
    }
    return render(request,"Admin/Bidding/print_asay_notice.html",context)




def VIEW_BID_DETAIL(request):
    biddings = SealedBid.objects.all()
    context = {
        "biddings":biddings
    }
    return render(request,"Admin/Bidding/view_bidding_details.html",context)








def ADD_PG_REQUIREMENT(request, id):
    bidding = get_object_or_404(SealedBid, id=id)

    # ❌ Prevent duplicate PG requirement
    if PerformanceBondRequirement.objects.filter(sealed_bid=bidding).exists():
        messages.error(request, "PG requirement already issued for this bidding.")
        return redirect("view_approved_projects")

    # ==========================
    # POST: SAVE DATA
    # ==========================
    if request.method == "POST":

        bid_approved_date_np = request.POST.get("bid_approved_date")
        required_amount = request.POST.get("performance_bond_amount_required")
        required_expiry_date_np = request.POST.get(
            "performance_bond_expiring_date_required"
        )

        # Nepali → English date converter
        def convert_nepali_date(date_str):
            if not date_str:
                return None
            y, m, d = map(int, date_str.split("-"))
            ey, em, ed = converter.nepali_to_english(y, m, d)
            return f"{ey}-{em:02d}-{ed:02d}"

        try:
            # ✅ Create PG Requirement
            PerformanceBondRequirement.objects.create(
                sealed_bid=bidding,
                bid_approved_date=convert_nepali_date(bid_approved_date_np),
                required_amount=required_amount or None,
                required_expiry_date=convert_nepali_date(required_expiry_date_np),
            )

            # ✅ UPDATE SEALED BID STATUS → Evaluated (1)
            bidding.status = 1
            bidding.save(update_fields=["status"])

            messages.success(
                request,
                "Performance Bond requirement issued and bidding marked as Evaluated."
            )

            return redirect("view_approved_projects")

        except Exception as e:
            messages.error(request, f"Error saving PG requirement: {e}")

    # ==========================
    # GET: SHOW FORM
    # ==========================
    context = {
        "bidding": bidding,
        "bidding_id": bidding.id,
        "project_name": bidding.project.name,
        "bidding_number": bidding.bidding_number,
    }

    return render(request, "Admin/Bidding/add_pg_detail.html", context)





def view_approved_projects(request):
    bidding = SealedBid.objects.all()
    context = {
        "bidding":bidding
    }
    return render(request,"Admin/Bidding/view_approved_projects.html",context)





from django.core.exceptions import ObjectDoesNotExist  

def print_contract_tippani(request,id):
    bidding = get_object_or_404(SealedBid, id=id)
   
    
    try:
        performancebond = PerformanceBondRequirement.objects.get(sealed_bid=bidding)
    except ObjectDoesNotExist:
        # Redirect to 'view_bidded_projects' if PerformanceBond does not exist
        messages.success(request, 'Records not existed!')
        return redirect('view_approved_projects')  # Replace 'view_bidded_projects' with your actual URL name
    
    
    evaluation_date_english = bidding.bid_evaluation_date
  
    performance_bond_expiring_date_english = performancebond.required_expiry_date
    bid_published_date_english = bidding.bid_published_date
    
    
    def convert_english_to_nepali(english_date_str):
        if english_date_str:
            english_year, english_month, english_day = map(int, english_date_str.split('-'))
            nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
            return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
        return None

    # Convert the start date from English to Nepali
    evaluation_date = convert_english_to_nepali(str(evaluation_date_english))

    performance_bond_expiring_date = convert_english_to_nepali(str(performance_bond_expiring_date_english))
    bid_published_date = convert_english_to_nepali(str(bid_published_date_english))
    

    
    
    context = {
        "bidding":bidding,
        "evaluation_date":evaluation_date,
        "performance_bond_expiring_date":performance_bond_expiring_date,
        "bid_published_date":bid_published_date
    }
    return render(request,"Admin/Bidding/print_contract_tippani.html",context)



def print_contract_invite(request,id):
    bidding = get_object_or_404(SealedBid, id=id)
    performancebond = PerformanceBondRequirement.objects.get(sealed_bid=bidding)
    evaluation_date_english = bidding.bid_evaluation_date
    performance_bond_expiring_date_required_english = performancebond.required_expiry_date
    performance_bond_amount_required = performancebond.required_amount
    
    
    def convert_english_to_nepali(english_date_str):
        if english_date_str:
            english_year, english_month, english_day = map(int, english_date_str.split('-'))
            nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
            return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
        return None

    # Convert the start date from English to Nepali
    evaluation_date = convert_english_to_nepali(str(evaluation_date_english))
    performance_bond_expiring_date_required = convert_english_to_nepali(str(performance_bond_expiring_date_required_english))

    
    
    context = {
        "bidding":bidding,
        "evaluation_date":evaluation_date,
        "performance_bond_expiring_date_required":performance_bond_expiring_date_required,
        "performance_bond_amount_required":performance_bond_amount_required
    }
    return render(request,"Admin/Bidding/print_contract_invite.html",context)




def add_pg_bank_detail(request, bidding_id):
    """
    Save Contract + Performance Bond Issued from the same form
    """

    # ==========================
    # FETCH SEALED BID
    # ==========================
    sealed_bid = get_object_or_404(SealedBid, id=bidding_id)

    # ==========================
    # GET OR CREATE CONTRACT
    # ==========================
    contract, created = Contract.objects.get_or_create(
        sealed_bid=sealed_bid
    )

    # ==========================
    # PREVENT DUPLICATE BOND
    # ==========================
    if PerformanceBondIssued.objects.filter(contract=contract).exists():
        messages.error(
            request,
            "कार्यसम्पादन जमानत पहिले नै दर्ता भइसकेको छ ।"
        )
        return redirect("view_agreement_projects")

    # ==========================
    # NEPALI → ENGLISH DATE
    # ==========================
    def nepali_to_english(date_str):
        if not date_str:
            return None
        y, m, d = map(int, date_str.split("-"))
        ey, em, ed = converter.nepali_to_english(y, m, d)
        return f"{ey}-{em:02d}-{ed:02d}"

    # ==========================
    # POST: SAVE DATA
    # ==========================
    if request.method == "POST":

        # ---- Performance Bond ----
        bank_name = request.POST.get("performance_bond_bank")
        bond_amount = request.POST.get("performance_bond_amount")
        bond_number = request.POST.get("performance_bond_number")

        bond_start_np = request.POST.get("performance_bond_start_date")
        bond_expiry_np = request.POST.get("performance_bond_expiring_date")

        # ---- Contract ----
        contract_date_np = request.POST.get("contract_date")
        contract_expire_np = request.POST.get("contract_expire_date")

        try:
            # ==========================
            # SAVE CONTRACT
            # ==========================
            contract.contract_date = nepali_to_english(contract_date_np)
            contract.contract_expire_date = nepali_to_english(contract_expire_np)
            contract.save()

            # ==========================
            # SAVE PERFORMANCE BOND ISSUED
            # ==========================
            PerformanceBondIssued.objects.create(
                contract=contract,
                bank_name=bank_name,
                bond_number=bond_number,
                issued_amount=bond_amount,
                issue_date=nepali_to_english(bond_start_np),
                expiry_date=nepali_to_english(bond_expiry_np),
            )

            # ==========================
            # UPDATE BID STATUS
            # ==========================
            sealed_bid.status = 3  # Contract Signed
            sealed_bid.save()

            messages.success(
                request,
                "सम्झौता र कार्यसम्पादन जमानत सफलतापूर्वक दर्ता गरियो ।"
            )
            return redirect("view_agreement_projects")

        except Exception as e:
            messages.error(request, f"त्रुटि भयो: {e}")

    # ==========================
    # GET: RENDER FORM
    # ==========================
    context = {
    "bidding_id": sealed_bid.id,   # ✅ REQUIRED
    "performancebond_id": contract.id,
    "project_name": sealed_bid.project.name,
    "bidding_number": sealed_bid.bidding_number,
    "bidder_name": sealed_bid.bidder_name_nepali,
        }

    return render(
        request,
        "Admin/Bidding/add_pg_bank_detail.html",
        context
    )




def view_agreement_projects(request):
    performancebond = PerformanceBondIssued.objects.all()
    context = {
        "performancebond":performancebond
    }
    return render(request,"Admin/Bidding/view_agreement_projects.html",context)




def print_contract_paper(request, id):
    """
    Print Government Contract Paper
    """

    # =============================
    # FETCH DATA
    # =============================
    bond_issued = get_object_or_404(PerformanceBondIssued, id=id)

    contract = bond_issued.contract
    sealed_bid = contract.sealed_bid
    project = sealed_bid.project

    # =============================
    # DATE CONVERTER (EN → NP)
    # =============================
    def english_to_nepali(date_obj):
        if not date_obj:
            return None
        y, m, d = date_obj.year, date_obj.month, date_obj.day
        ny, nm, nd = converter.english_to_nepali(y, m, d)
        return f"{ny}-{nm:02d}-{nd:02d}"

    # =============================
    # CONTEXT
    # =============================
    context = {
        # Objects
        "bond_issued": bond_issued,
        "contract": contract,
        "bidding": sealed_bid,
        "project": project,

        # Contractor
        "contractor_name_nepali": sealed_bid.bidder_name_nepali,
        "contractor_name_english": sealed_bid.bidder_name_english,
        "bidder_owner_nepali": sealed_bid.bidder_owner_nepali,
        "bidder_address_nepali": sealed_bid.bidder_address_nepali,

        # Project
        "project_name_nepali": project.name,
        "project_address": project.address,

        # Financial
        "bidding_amount": sealed_bid.bidding_amount,
        "cost_etimate": sealed_bid.cost_estimate_vat,

        # Dates (Nepali)
        "contract_date_nepali": english_to_nepali(contract.contract_date),
        "contract_expire_date_nepali": english_to_nepali(contract.contract_expire_date),
    }

    return render(
        request,
        "Admin/Bidding/print_contract_paper.html",
        context
    )



from django.db.models import Sum

def print_bid_work_order(request, id):
    performancebond = get_object_or_404(PerformanceBondIssued, id=id)

    # Access contract expire date correctly
    contract_expire_date_english = performancebond.contract.contract_expire_date

    def convert_english_to_nepali(english_date):
        if english_date:
            nepali_year, nepali_month, nepali_day = converter.english_to_nepali(
                english_date.year,
                english_date.month,
                english_date.day
            )
            return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
        return None

    contract_expire_date_nepali = convert_english_to_nepali(contract_expire_date_english)

    context = {
        "performancebond": performancebond,
        "contract_expire_date_nepali": contract_expire_date_nepali,
    }

    return render(request, "Admin/Bidding/print_work_order.html", context)

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import SealedBid, Contract

def get_sealed_bid_contract_info(request, sealed_bid_id):
    """
    Return contract info for a Contract Signed SealedBid
    """

    bid = get_object_or_404(SealedBid, id=sealed_bid_id)
    if not hasattr(bid, "contract"):
        return JsonResponse({"error": "सम्झौता भएको छैन"}, status=404)

    return JsonResponse({
        "bidding_number": bid.bidding_number,
        "bidder_name": bid.bidder_name_nepali,
        "bidder_address": bid.bidder_address_nepali,
        "contract_id": bid.contract.id,
    })

from django.db import transaction
import traceback
# ----------------------------
# Add Advance Payment + BG
# ----------------------------
def add_advance_payment(request):

    # 🔹 Only Contract Signed Sealed Bids
    sealed_bids = (
        SealedBid.objects
        .filter(status=3, contract__isnull=False)
        .select_related("project", "contract")
    )

    # =========================
    # POST
    # =========================
    if request.method == "POST":
        try:
            with transaction.atomic():

                # -------------------------
                # Contract
                # -------------------------
                contract_id = request.POST.get("contract_id")
                if not contract_id:
                    raise ValueError("Contract चयन गरिएको छैन।")

                contract = get_object_or_404(Contract, id=contract_id)

                # -------------------------
                # Advance Amount
                # -------------------------
                approved_amount = request.POST.get("approved_amount")
                if not approved_amount:
                    raise ValueError("अग्रिम भुक्तानी रकम अनिवार्य छ।")

                approved_amount = Decimal(approved_amount)

                if approved_amount <= 0:
                    raise ValueError("अग्रिम भुक्तानी रकम ० भन्दा बढी हुनुपर्छ।")

                # -------------------------
                # Approval Date
                # -------------------------
                approval_date_np = request.POST.get("approval_date")
                if not approval_date_np:
                    raise ValueError("स्वीकृत मिति अनिवार्य छ।")

                approval_date_en = convert_nepali_to_english(approval_date_np)

                # -------------------------
                # OPTIONAL: total advance limit
                # -------------------------
                total_advance = (
                    AdvancePayment.objects
                    .filter(contract=contract)
                    .aggregate(total=Sum("approved_amount"))["total"] or Decimal("0")
                )

                contract_amount = contract.sealed_bid.bidding_amount or Decimal("0")

                if total_advance + approved_amount > contract_amount:
                    raise ValueError(
                        "कुल अग्रिम भुक्तानी ठेक्का रकम भन्दा बढी हुन सक्दैन।"
                    )

                # -------------------------
                # Create Advance Payment
                # -------------------------
                advance_payment = AdvancePayment.objects.create(
                    contract=contract,
                    approved_amount=approved_amount,
                    approval_date=approval_date_en,
                    remarks=request.POST.get("remarks"),
                )

                # -------------------------
                # Bank Guarantee
                # -------------------------
                guaranteed_amount = Decimal(
                    request.POST.get("guaranteed_amount", "0")
                )

                if guaranteed_amount < approved_amount:
                    raise ValueError(
                        "जमानत रकम अग्रिम भुक्तानी भन्दा कम हुन सक्दैन।"
                    )

                AdvanceBankGuarantee.objects.create(
                    advance_payment=advance_payment,
                    bank_name=request.POST.get("bank_name"),
                    guarantee_number=request.POST.get("guarantee_number"),
                    guaranteed_amount=guaranteed_amount,
                    issue_date=convert_nepali_to_english(
                        request.POST.get("issue_date")
                    ),
                    expiry_date=convert_nepali_to_english(
                        request.POST.get("expiry_date")
                    ),
                    document=request.FILES.get("document"),
                )

                messages.success(
                    request,
                    "अग्रिम भुक्तानी तथा अग्रिम बैंक जमानत सफलतापूर्वक दर्ता गरियो।"
                )

                return redirect("print_advance_tippani", id=advance_payment.id)

        except Exception as e:
            traceback.print_exc()
            messages.error(request, f"त्रुटि भयो: {e}")

            return render(
                request,
                "Admin/Bidding/add_advance_payment.html",
                {
                    "sealed_bids": sealed_bids,
                    "error": str(e),
                }
            )

    # =========================
    # GET
    # =========================
    return render(
        request,
        "Admin/Bidding/add_advance_payment.html",
        {
            "sealed_bids": sealed_bids
        }
    )


# ==========================
# ADVANCE PAYMENT - TIPPANI (DECISION NOTE)
# ==========================
def print_advance_tippani(request, id):
    """
    Print the decision note (टिप्पणी) for an Advance Payment + Advance Bank
    Guarantee, for योजना शाखा / लेखा शाखा / प्रमुख प्रशासकिय अधिकृत sign-off.
    """
    advance_payment = get_object_or_404(AdvancePayment, id=id)
    contract = advance_payment.contract
    sealed_bid = contract.sealed_bid
    project = sealed_bid.project

    try:
        bank_guarantee = advance_payment.bank_guarantee
    except AdvanceBankGuarantee.DoesNotExist:
        bank_guarantee = None

    context = {
        "advance_payment": advance_payment,
        "bank_guarantee": bank_guarantee,
        "contract": contract,
        "sealed_bid": sealed_bid,
        "project": project,

        "today_nepali": convert_english_to_nepali(datetime.date.today()),
        "approval_date_nepali": convert_english_to_nepali(advance_payment.approval_date),
        "issue_date_nepali": convert_english_to_nepali(bank_guarantee.issue_date) if bank_guarantee else None,
        "expiry_date_nepali": convert_english_to_nepali(bank_guarantee.expiry_date) if bank_guarantee else None,
    }

    return render(request, "Admin/Bidding/print_advance_tippani.html", context)


# ==========================
# EXTENSION (CONTRACT + PG)
# ==========================
def extend_performance_bond(request, id):
    """पुरानो पेज: अब कार्यप्रवाहको म्याद थप फारममा (?next= सहित)."""
    from urllib.parse import quote

    from django.urls import reverse

    bond = get_object_or_404(PerformanceBondIssued, id=id)
    url = reverse("bid_wf_extension", args=[bond.contract.sealed_bid.project_id])
    nxt = request.GET.get("next")
    return redirect(url + (f"?next={quote(nxt, safe='/?=&')}" if nxt else ""))


def update_performance_bond_expiry(request):
    """पुरानो POST: नियम जाँच नहुने भएकाले बन्द — नयाँ फारममा पठाउने."""
    bond = PerformanceBondIssued.objects.filter(id=request.POST.get("bond_id") or 0).first()
    if bond is None:
        return redirect("performance_guarantees")
    messages.info(request, "म्याद थप अब यही फारमबाट — निवेदन मिति, कारण र निर्णय सहित।")
    return redirect("bid_wf_extension", bond.contract.sealed_bid.project_id)



def view_performance_bank_guarantees(request):
    return render(
        request,
        "Admin/Bidding/view_performance_bank_guarantees.html",
        {"performancebond": PerformanceBondIssued.objects.all()},
    )



from django.shortcuts import render, get_object_or_404
from django.contrib import messages
from datetime import date

def print_performance_bond_tippani(request, id):
    bond = get_object_or_404(PerformanceBondIssued, id=id)
    contract = bond.contract
    sealed_bid = contract.sealed_bid
    project = sealed_bid.project

    # ----------------------------
    # CURRENT (LATEST) DATES
    # ----------------------------
    current_pg_expiry = bond.current_expiry_date
    current_contract_expiry = contract.current_expiry_date

    # ----------------------------
    # LAST EXTENSIONS (IF ANY)
    # ----------------------------
    last_pg_extension = (
        bond.extensions.order_by("-extended_expiry_date").first()
    )

    last_contract_extension = (
        contract.extensions.order_by("-extended_expiry_date").first()
        if hasattr(contract, "extensions")
        else None
    )

    context = {
        # Objects
        "bond": bond,
        "contract": contract,
        "project": project,
        "sealed_bid": sealed_bid,

        # Contractor
        "bidder_name": sealed_bid.bidder_name_nepali,
        "bidding_number": sealed_bid.bidding_number,

        # Amounts
        "bidding_amount": sealed_bid.bidding_amount,
        "pg_amount": bond.issued_amount,

        # ORIGINAL DATES (Nepali)
        "original_pg_expiry_nepali": convert_english_to_nepali(
            bond.expiry_date
        ),
        "original_contract_expiry_nepali": convert_english_to_nepali(
            contract.contract_expire_date
        ),

        # CURRENT (LATEST) DATES (Nepali)
        "current_pg_expiry_nepali": convert_english_to_nepali(
            current_pg_expiry
        ),
        "current_contract_expiry_nepali": convert_english_to_nepali(
            current_contract_expiry
        ),

        # EXTENSION INFO
        "pg_extended": last_pg_extension is not None,
        "contract_extended": last_contract_extension is not None,

        "pg_extension_remarks": (
            last_pg_extension.remarks if last_pg_extension else ""
        ),
        "contract_extension_remarks": (
            last_contract_extension.remarks if last_contract_extension else ""
        ),

        # Today
        "today_nepali": convert_english_to_nepali(date.today()),
    }

    return render(
        request,
        "Admin/Bidding/print_performance_bond_tippani.html",
        context
    )



def view_advance_bank_guarantees(request):
    return render(
        request,
        "Admin/Bidding/view_advance_bank_guarantees.html",
        {
            "advance_bgs": AdvanceBankGuarantee.objects.select_related(
                "advance_payment__contract__sealed_bid__project"
            ).all()
        }
    )
    



import logging



logger = logging.getLogger(__name__)

def add_final_payment(request):

    contracts = list(
        Contract.objects
        .select_related("sealed_bid__project")
        .filter(sealed_bid__status=3)
        .annotate(
            total_advance=Sum("advance_payments__approved_amount")
        )
        .prefetch_related("running_evaluations")
    )

    # 🔹 Attach running-bill summary per contract, for the dropdown's
    # data-* attributes (used to prefill/toggle the running-bill fields).
    for c in contracts:
        running_evals = list(c.running_evaluations.all())
        c.has_running_bill = bool(running_evals)
        c.running_bill_total = sum(
            (rev.net_payable for rev in running_evals), Decimal("0")
        )
        if running_evals:
            latest_running_eval = max(running_evals, key=lambda rev: rev.evaluation_date)
            c.latest_eval_amount = latest_running_eval.total_evaluated_amount
        else:
            c.latest_eval_amount = Decimal("0")

    if request.method == "POST":
        try:
            with transaction.atomic():

                contract_id = request.POST.get("contract_id")
                if not contract_id:
                    raise ValueError("ठेक्का चयन गरिएको छैन।")

                contract = get_object_or_404(Contract, id=contract_id)

                if FinalPayment.objects.filter(contract=contract).exists():
                    raise ValueError("यो ठेक्काको अन्तिम भुक्तानी पहिले नै सुरक्षित गरिएको छ।")

                bidding_amount = contract.sealed_bid.bidding_amount or Decimal("0")

                db_total_advance = (
                    AdvancePayment.objects
                    .filter(contract=contract)
                    .aggregate(total=Sum("approved_amount"))
                    .get("total") or Decimal("0")
                )

                posted_advance = Decimal(
                    request.POST.get("total_advance") or db_total_advance
                )

                if posted_advance < db_total_advance:
                    raise ValueError("अग्रिम भुक्तानी रकम घटाउन मिल्दैन।")

                # 🔹 Running bill (if this contract has any) — always taken
                # from the DB, never trusted from the client.
                has_running_bill = contract.running_evaluations.exists()
                db_running_total = contract.total_running_paid  # Contract.total_running_paid property

                total_evaluation_amount = Decimal(
                    request.POST.get("total_evaluation_amount") or 0
                )
                if total_evaluation_amount <= 0:
                    raise ValueError("कुल मूल्याङ्कन रकम अनिवार्य छ।")

                agrim_tax = Decimal(request.POST.get("agrim_tax") or 0)
                vat_deduction = Decimal(request.POST.get("vat_deduction") or 0)
                dharauti_deduction = Decimal(request.POST.get("dharauti_deduction") or 0)
                bahal_tax = Decimal(request.POST.get("bahal_tax") or 0)
                tax_total = agrim_tax + vat_deduction + dharauti_deduction + bahal_tax

                # 🔹 खुद भुक्तानी रकम बेस:
                # रनिङ बिल लिइसकेको भए -> कुल मूल्याङ्कन रकम - कुल रनिङ बिल रकम
                # अन्यथा                -> कुल मूल्याङ्कन रकम - कुल अग्रिम भुक्तानी
                if has_running_bill:
                    base_amount = total_evaluation_amount - db_running_total
                else:
                    base_amount = total_evaluation_amount - posted_advance

                computed_final_amount = base_amount - tax_total

                # 🔹 खुद भुक्तानी रकम अब सम्पादन योग्य (editable) छ — प्रयोगकर्ताले
                # आफैं सच्याएको मान भए सोही प्रयोग गर्ने, नत्र स्वतः गणना गरिएको मान।
                posted_final_amount = request.POST.get("final_amount")
                if posted_final_amount not in (None, ""):
                    final_amount = Decimal(posted_final_amount)
                else:
                    final_amount = computed_final_amount

                if final_amount <= 0:
                    raise ValueError("खुद भुक्तानी रकम शून्य वा ऋणात्मक हुन सक्दैन।")

                # 🔹 DATE FIX (THIS WAS THE ROOT CAUSE)
                payment_date_np = request.POST.get("payment_date")
                payment_date = convert_nepali_to_english(payment_date_np)

                if not payment_date:
                    raise ValueError("अमान्य नेपाली मिति")

                remarks = request.POST.get("remarks", "")

                final_payment = FinalPayment.objects.create(
                    contract=contract,
                    bidding_amount=bidding_amount,
                    total_advance_payment=posted_advance,
                    total_evaluation_amount=total_evaluation_amount,
                    total_running_bill_amount=db_running_total if has_running_bill else Decimal("0"),
                    agrim_tax=agrim_tax,
                    vat_deduction=vat_deduction,
                    dharauti_deduction=dharauti_deduction,
                    bahal_tax=bahal_tax,
                    final_amount=final_amount,
                    payment_date=payment_date,
                    remarks=remarks,
                )

                messages.success(
                    request,
                    "अन्तिम भुक्तानी सफलतापूर्वक सुरक्षित गरियो।"
                )

                return redirect("print_final_tippani", id=final_payment.id)

        except Exception as e:
            print("\n" + "="*60)
            print("🔥 FINAL PAYMENT ERROR 🔥")
            print("Exception Type:", type(e))
            print("Exception Message:", e)
            print("Full Traceback ↓↓↓")
            traceback.print_exc()
            print("="*60 + "\n")

            messages.error(request, f"त्रुटि भयो: {e}")

    return render(
        request,
        "Admin/Bidding/add_final_payment.html",
        {"contracts": contracts}
    )
    
    
def add_running_evaluation(request):

    contracts = (
        Contract.objects
        .select_related("sealed_bid__project")
        .filter(sealed_bid__status=3)
    )

    if request.method == "POST":
        try:
            with transaction.atomic():

                contract_id = request.POST.get("contract_id")
                contract = get_object_or_404(Contract, id=contract_id)

                evaluation_date = convert_nepali_to_english(
                    request.POST.get("evaluation_date")
                )
                if not evaluation_date:
                    raise ValueError("अमान्य मूल्याङ्कन मिति")

                total_evaluated_amount = Decimal(
                    request.POST.get("total_evaluated_amount") or 0
                )

                payable_amount = Decimal(
                    request.POST.get("payable_amount") or 0
                )

                advance_adjusted = Decimal(
                    request.POST.get("advance_adjusted") or 0
                )

                agrim_tax = Decimal(request.POST.get("agrim_tax") or 0)
                vat_deduction = Decimal(request.POST.get("vat_deduction") or 0)
                dharauti_deduction = Decimal(request.POST.get("dharauti_deduction") or 0)
                bahal_tax = Decimal(request.POST.get("bahal_tax") or 0)

                # 🔹 Prevent over-evaluation
                if total_evaluated_amount > contract.sealed_bid.bidding_amount:
                    raise ValueError("कुल मूल्याङ्कन ठेक्का रकमभन्दा बढी हुन सक्दैन।")

                deductions = (
                    advance_adjusted +
                    agrim_tax +
                    vat_deduction +
                    dharauti_deduction +
                    bahal_tax
                )

                net_payable = payable_amount - deductions

                if net_payable <= 0:
                    raise ValueError("खुद भुक्तानी रकम शून्य वा ऋणात्मक हुन सक्दैन।")

                running_evaluation = RunningEvaluation.objects.create(
                    contract=contract,
                    evaluation_date=evaluation_date,
                    total_evaluated_amount=total_evaluated_amount,
                    payable_amount=payable_amount,
                    advance_adjusted=advance_adjusted,
                    agrim_tax=agrim_tax,
                    vat_deduction=vat_deduction,
                    dharauti_deduction=dharauti_deduction,
                    bahal_tax=bahal_tax,
                    net_payable=net_payable,
                    remarks=request.POST.get("remarks", "")
                )

                messages.success(request, "Running Evaluation सुरक्षित गरियो।")
                return redirect("print_running_tippani", id=running_evaluation.id)

        except Exception as e:
            messages.error(request, f"त्रुटि भयो: {e}")

    return render(
        request,
        "Admin/Bidding/add_running_evaluation.html",
        {"contracts": contracts}
    )


# ==========================
# RUNNING BILL - TIPPANI (DECISION NOTE)
# ==========================
def print_running_tippani(request, id):
    """
    Print the decision note (टिप्पणी) for a Running Bill / Running Evaluation,
    for योजना शाखा / लेखा शाखा / प्रमुख प्रशासकिय अधिकृत sign-off.
    """
    running_evaluation = get_object_or_404(RunningEvaluation, id=id)
    contract = running_evaluation.contract
    sealed_bid = contract.sealed_bid
    project = sealed_bid.project

    context = {
        "running_evaluation": running_evaluation,
        "contract": contract,
        "sealed_bid": sealed_bid,
        "project": project,

        "today_nepali": convert_english_to_nepali(datetime.date.today()),
        "evaluation_date_nepali": convert_english_to_nepali(running_evaluation.evaluation_date),
    }

    return render(request, "Admin/Bidding/print_running_tippani.html", context)


def view_advance_payment(request):
    return render(
        request,
        "Admin/Bidding/view_advance_payments.html",
        {
            "advance_payments": AdvancePayment.objects.select_related(
                "contract__sealed_bid__project"
            ).all()
        }
    )
    
    
    
def view_running_evaluations(request):
    return render(
        request,
        "Admin/Bidding/view_running_evaluations.html",
        {
            "running_evaluations": (
                RunningEvaluation.objects
                .select_related("contract__sealed_bid__project")
                .order_by("evaluation_date")
            )
        }
    )
    
    
def view_final_payment(request):
    return render(
        request,
        "Admin/Bidding/view_final_payment.html",
        {
            "final_payments": (
                FinalPayment.objects
                .select_related("contract__sealed_bid__project")
                .order_by("-payment_date")
            )
        }
    )


# ==========================
# FINAL PAYMENT - TIPPANI (DECISION NOTE)
# ==========================
def print_final_tippani(request, id):
    """
    Print the decision note (टिप्पणी) for a Final Payment, for
    योजना शाखा / लेखा शाखा / प्रमुख प्रशासकिय अधिकृत sign-off.
    """
    final_payment = get_object_or_404(FinalPayment, id=id)
    contract = final_payment.contract
    sealed_bid = contract.sealed_bid
    project = sealed_bid.project

    context = {
        "final_payment": final_payment,
        "contract": contract,
        "sealed_bid": sealed_bid,
        "project": project,

        "today_nepali": convert_english_to_nepali(datetime.date.today()),
        "payment_date_nepali": convert_english_to_nepali(final_payment.payment_date),
        # रनिङ बिलमा कट्टी भइसकेको बाहेक बाँकी अग्रिम
        "advance_left": max(
            (final_payment.total_advance_payment or Decimal("0"))
            - (contract.running_evaluations.aggregate(t=Sum("advance_adjusted"))["t"] or Decimal("0")),
            Decimal("0"),
        ),
    }

    return render(request, "Admin/Bidding/print_final_tippani.html", context)