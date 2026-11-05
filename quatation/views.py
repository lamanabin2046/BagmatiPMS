from django.shortcuts import render

# Create your views here.

from django.shortcuts import render, redirect, HttpResponse
from accounts.models import *
from django.http import HttpResponseForbidden
from django.contrib.auth import login, logout
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from nepali.date_converter import converter
from usercommittee.models import CostEstimate
from .models import Suchikrit, Quation, QuationFinal
from projects.models import Project


def ADD_SUCHIKRIT_LIST(request):
    if request.method == "POST":
        firm_name = request.POST.get('firm_name')
        firm_owner = request.POST.get('firm_owner')
        firm_address = request.POST.get('firm_address')
        firm_pan = request.POST.get('firm_pan')
        firm_contact = request.POST.get('firm_contact')
        suchikrit_date_nepali = request.POST.get('suchikrit_date')

        
        
        def convert_nepali_to_english(nepali_date_str):
            if nepali_date_str:
                nepali_year, nepali_month, nepali_day = map(int, nepali_date_str.split('-'))
                english_year, english_month, english_day = converter.nepali_to_english(nepali_year, nepali_month, nepali_day)
                return f"{english_year}-{english_month:02d}-{english_day:02d}"
            return None

        # Convert Nepali dates to English dates
        suchikrit_date = convert_nepali_to_english(suchikrit_date_nepali)

        suchikrit = Suchikrit(
            firm_name=firm_name,
            firm_owner=firm_owner,
            firm_address =firm_address,
            firm_pan =firm_pan,
            firm_contact=firm_contact,
            suchikrit_date=suchikrit_date
         
        )
        suchikrit.save()
        messages.success(request, 'Saved Successfully')
        return redirect('view_suchikrit_list')   
    return render(request,"Admin/Quatation/add_suchikrit.html")


def VIEW_SUCHIKRIT_LIST(request):
    suchikrit = Suchikrit.objects.all()
    context ={
        "suchikrit":suchikrit
    }
    return render(request,"Admin/Quatation/view_suchikrit.html",context )



from django.http import HttpResponse
from django.core.exceptions import ValidationError



from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.contrib import messages


def INVITE_QUATATION(request):
    if request.method == 'POST':
        project_id = request.POST.get('project')
        firm_ids = request.POST.getlist('firms')
        cost_estimate = request.POST.get('cost_estimate')
        contingency = request.POST.get('contingency')

        try:
            # Fetch the project
            project = Project.objects.get(id=project_id)

            # Check if a Quation already exists for this project
            if Quation.objects.filter(project=project).exists():
                messages.warning(request, "Quotation already exists for this project.")
                return redirect('invite_quatation')

            # Fetch the firms
            firms = Suchikrit.objects.filter(id__in=firm_ids)

            # Create a Quation instance
            quation = Quation.objects.create(
                project=project,
                cost_estimate=cost_estimate,
                contingency=contingency,
                is_invited=True
            )
            quation.suchikrit.set(firms)  # Assign the firms to the quation
            quation.save()
            project.status = 1
            project.save()

            # If successful, show a success message
            messages.success(request, "Firms have been successfully invited to bid!")
            return redirect('view_quatation_projects')

        except Project.DoesNotExist:
            messages.error(request, "Invalid project selected.")
        except Suchikrit.DoesNotExist:
            messages.error(request, "One or more firms not found.")
        except ValidationError as e:
            messages.error(request, f"Validation Error: {str(e)}")
        except Exception as e:
            messages.error(request, f"An unexpected error occurred: {str(e)}")

    # Fetch all the projects and firms
    projects = Project.objects.filter(procurement_type=3, status=0)
    firms = Suchikrit.objects.all()

    return render(request, 'Admin/Quatation/invite_quatation.html', {'projects': projects, 'firms': firms})





def VIEW_QUATATION_PROJECTS(request):
    # Fetch all Quation objects with related Project data
    quations = Quation.objects.all().select_related('project').prefetch_related('suchikrit')
    processed_quations = []
    
    for quation in quations:
        # Initialize lowest bidder variables
        lowest_bidder = None
        lowest_price = None
        
        # Check if bidded_prices is not empty and parse it
        if quation.bidded_prices:
            try:
                bidded_prices_data = json.loads(quation.bidded_prices)  # Parse the JSON string to a Python dictionary
                for project_name, bids in bidded_prices_data.items():
                    for bid in bids:
                        for firm_name, price in bid.items():
                            if lowest_price is None or price < lowest_price:
                                lowest_price = price
                                lowest_bidder = firm_name
            except json.JSONDecodeError:
                print(f"Error decoding bidded_prices for Quation ID {quation.id}")
        
        # Create a dictionary to hold the quation data
        quation_data = {
            'id': quation.id,  # Include the ID field
            'project_name': quation.project.name,
            'budget': quation.project.budget,
            'cost_estimate': quation.cost_estimate,
            'contingency': quation.contingency,
            'firm_names': ', '.join(firm.firm_name for firm in quation.suchikrit.all()),  # Concatenate firm names
            'lowest_firm_name': lowest_bidder,  # Add the lowest bidder firm name
            'lowest_price': lowest_price,  # Add the lowest bid price
        }
        processed_quations.append(quation_data)

    context = {
        "quations": processed_quations  # Pass the processed data to the template
    }
    
    return render(request, "Admin/Quatation/view_quatation_project.html", context)


from django.shortcuts import get_object_or_404, redirect
import json

from django.db import transaction
from django.shortcuts import get_object_or_404, render, redirect
from django.db import transaction
from django.http import HttpResponse
import json



def ADD_QUATATION_AMOUNT(request, id):
    quatation = get_object_or_404(Quation, id=id)

    # Get all associated Suchikrit firms for this quotation
    suchikrit_firms = quatation.suchikrit.all()

    # Initialize the bidded prices data
    bidded_data = []

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Loop through each firm and its corresponding bidded price
                for firm in suchikrit_firms:
                    bidded_price = request.POST.get(f'bid_price_{firm.id}')
                    if bidded_price:
                        # Append firm name and bidded price as a dictionary
                        bidded_data.append({firm.firm_name: float(bidded_price)})

                # Ensure the structure is correct
                project_name = quatation.project.name
                bidded_prices_dict = {project_name: bidded_data}

                # Print the data before saving for debugging purposes
                print("Final Bidded Prices Structure:", bidded_prices_dict)

                # Now save all bidded data in a single record for the quotation
                quatation.bidded_prices = json.dumps(bidded_prices_dict, ensure_ascii=False)

                # Save the quotation
                quatation.save()

            return redirect('view_quatation_projects')  # Redirect after saving
        except Exception as e:
            # Handle exceptions, log errors, or return a meaningful message
            print(f"Error: {e}")
            return HttpResponse(f"An error occurred: {e}", status=400)

    context = {
        "quatation": quatation,
        "suchikrit_firms": suchikrit_firms,
    }

    return render(request, "Admin/Quatation/add_quatation_amount.html", context)



import json
from django.shortcuts import render, get_object_or_404

def PRINT_QUATATION_TIPPANI(request, id):
    # Retrieve the Quation instance by its id
    quatation = get_object_or_404(Quation, id=id)

    # Get all associated firms with their names and addresses
    associated_firms = quatation.suchikrit.values('firm_name', 'firm_address')

    context = {
        "quatation": quatation,
        "associated_firms": list(associated_firms),  # Convert QuerySet to a list of dictionaries
    }

    return render(request, "Admin/Quatation/print_quatation_tippani.html", context)

def SEND_QUATATION_LETTER(request, id):
    quatation = get_object_or_404(Quation, id=id)

    # Get all associated firms with their names and addresses
    associated_firms = quatation.suchikrit.values('firm_name', 'firm_address')

    # Access fiscalyear, ward, project name, and cost_estimate
    fiscalyear = quatation.project.fiscalyear.name  # Assuming project.fiscalyear is the correct field path
    ward = quatation.project.ward.name  # Assuming project.ward is the correct field path
    project_name = quatation.project.name  # Assuming quatation.project.name gives the project name
    cost_estimate = quatation.cost_estimate  # Assuming quatation has the cost_estimate field

    context = {
        "quatation": quatation,
        "associated_firms": list(associated_firms),  # Convert QuerySet to a list of dictionaries
        "fiscalyear": fiscalyear,
        "ward": ward,
        "project_name": project_name,
        "cost_estimate": cost_estimate,
    }

    return render(request, "Admin/Quatation/send_quatation_letter.html", context)




def APPROVED_QUATATION_TIPPANI(request, id):
    """न्यूनतम दरभाउपत्र स्वीकृत गरी सम्झौता तथा कार्यादेशको टिप्पणी (प्राप्त सबै दरको तुलना सहित)."""
    from datetime import date

    from usercommittee.workflow import bs_date

    from .workflow import bids

    quatation = get_object_or_404(Quation, id=id)
    firms = {f.firm_name: f for f in quatation.suchikrit.all()}
    pairs = sorted(bids(quatation), key=lambda x: x[1])
    extracted_bids = []
    for i, (firm, price) in enumerate(pairs):
        f = firms.get(firm) or Suchikrit.objects.filter(firm_name=firm).first()
        extracted_bids.append({"firm_name": firm, "bidded_price": price, "firm_address": f.firm_address if f else "",
                               "lowest": i == 0})
    lowest = extracted_bids[0] if extracted_bids else {}
    approval = getattr(quatation, "approval", None)
    estimate = quatation.cost_estimate or 0
    below = round((estimate - lowest["bidded_price"]) * 100 / estimate, 2) if lowest and estimate else None

    context = {
        "quatation": quatation,
        "extracted_bids": extracted_bids,
        "lowest_firm_name": lowest.get("firm_name"),
        "lowest_bidded_price": lowest.get("bidded_price"),
        "lowest_firm_address": lowest.get("firm_address", ""),
        "below_pct": below,
        "invited_count": len(firms),
        "received_count": len(pairs),
        "invite_date_nepali": bs_date(quatation.invite_date),
        "opening_date_nepali": bs_date(quatation.opening_date),
        # टिप्पणीको मिति: स्वीकृत भएको मिति, नभए आज
        "application_date_nepali": bs_date(approval.approved_at.date() if approval else date.today()),
    }
    return render(request, "Admin/Quatation/approved_quatation_tippani.html", context)


def ADD_QUATATION_AGREEMENT(request, id):
    if request.method == "POST":
        agreement_date_nepali = request.POST.get("agreement_date")
        expire_date_nepali = request.POST.get("expire_date")
        quatation_id = request.POST.get("quatation_id")
        quatation = Quation.objects.get(id = quatation_id)

        
        def convert_nepali_to_english(nepali_date_str):
            if nepali_date_str:
                nepali_year, nepali_month, nepali_day = map(int, nepali_date_str.split('-'))
                english_year, english_month, english_day = converter.nepali_to_english(nepali_year, nepali_month, nepali_day)
                return f"{english_year}-{english_month:02d}-{english_day:02d}"
            return None

        # Convert Nepali dates to English dates
        agreement_date_english = convert_nepali_to_english(agreement_date_nepali)
        expire_date_english = convert_nepali_to_english(expire_date_nepali)
    
        
        
        quatation.agreement_date =agreement_date_english
        quatation.expire_date = expire_date_english
        quatation.save()
        return redirect("print_quatation_agreement",id=quatation_id)
        
        
        
    
    quatation = get_object_or_404(Quation, id=id)
    project_name = quatation.project.name
   

    # Parse the JSON string from the 'bidded_prices' field
    try:
        bidded_prices = json.loads(quatation.bidded_prices)
    except json.JSONDecodeError:
        bidded_prices = {}

    # Prepare the extracted data for passing to the template
    extracted_bids = []
    for firm_name, bids in bidded_prices.items():
        for bid in bids:
            for firm, price in bid.items():
                try:
                    suchikrit_firm = Suchikrit.objects.get(firm_name=firm)
                    firm_address = suchikrit_firm.firm_address
                except Suchikrit.DoesNotExist:
                    firm_address = "Address not found"
                extracted_bids.append({
                    "firm_name": firm,
                    "bidded_price": price,
                    "firm_address": firm_address,
                })

    # Find the lowest bidded_price and associated firm_name
    if extracted_bids:
        lowest_bid = min(extracted_bids, key=lambda x: x["bidded_price"])
        lowest_firm_name = lowest_bid["firm_name"]
        lowest_firm_address = lowest_bid["firm_address"]
        lowest_bidded_price = lowest_bid["bidded_price"]
    else:
        lowest_firm_name = None
        lowest_firm_address = None
        lowest_bidded_price = None

    context = {
        "quatation": quatation,
        "quatation_id": quatation.id,  # Adding the ID of the quatation
        "extracted_bids": extracted_bids,
        "lowest_firm_name": lowest_firm_name,
        "lowest_bidded_price": lowest_bidded_price,
        "lowest_firm_address": lowest_firm_address,
        "project_name": project_name,
    }

    return render(request, "Admin/Quatation/add_quatation_agreement.html", context)


def PRINT_QUATATION_AGREEMENT(request, id):
    quatation = get_object_or_404(Quation, id=id)
    agreement_date_english = quatation.agreement_date
    expire_date_english = quatation.expire_date
    
    def convert_english_to_nepali(english_date_str):
        if english_date_str:
            english_year, english_month, english_day = map(int, english_date_str.split('-'))
            nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
            return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
        return None

    # Convert the start date from English to Nepali
    agreement_date_nepali = convert_english_to_nepali(str(agreement_date_english))
    expire_date_nepali = convert_english_to_nepali(str(expire_date_english))
    
    
    
    

    try:
        bidded_prices = json.loads(quatation.bidded_prices)
    except (json.JSONDecodeError, AttributeError):
        bidded_prices = {}

    extracted_bids = []
    for firm_name, bids in bidded_prices.items():
        for bid in bids:
            for firm, price in bid.items():
                try:
                    suchikrit_firm = Suchikrit.objects.get(firm_name=firm)
                    firm_address = suchikrit_firm.firm_address
                    firm_owner = suchikrit_firm.firm_owner
                except Suchikrit.DoesNotExist:
                    firm_address = "Address not found"
                    firm_owner = "Owner not found"
                extracted_bids.append({
                    "firm_name": firm,
                    "bidded_price": price,
                    "firm_address": firm_address,
                    "firm_owner": firm_owner,
                })

    if extracted_bids:
        lowest_bid = min(extracted_bids, key=lambda x: x["bidded_price"])
        lowest_firm_name = lowest_bid["firm_name"]
        lowest_bidded_price = lowest_bid["bidded_price"]
        lowest_firm_address = lowest_bid["firm_address"]
        lowest_firm_onwer = lowest_bid["firm_owner"]
    else:
        lowest_firm_name = "N/A"
        lowest_bidded_price = "N/A"
        lowest_firm_address = "N/A"
        lowest_firm_onwer = "N/A"

    context = {
        "quatation": quatation,
        "extracted_bids": extracted_bids,
        "lowest_firm_name": lowest_firm_name,
        "lowest_bidded_price": lowest_bidded_price,
        "lowest_firm_address": lowest_firm_address,
        "lowest_firm_onwer": lowest_firm_onwer,
        "agreement_date_nepali":agreement_date_nepali,
        "expire_date_nepali":expire_date_nepali
        
    }

    return render(request, "Admin/Quatation/print_quatation_agreement.html", context)




def PRINT_QUATATION_WORK_ORDE(request,id):
    quatation = get_object_or_404(Quation, id=id)
    agreement_date_english = quatation.agreement_date
    expire_date_english = quatation.expire_date
    
    def convert_english_to_nepali(english_date_str):
        if english_date_str:
            english_year, english_month, english_day = map(int, english_date_str.split('-'))
            nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
            return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
        return None

    # Convert the start date from English to Nepali
    agreement_date_nepali = convert_english_to_nepali(str(agreement_date_english))
    expire_date_nepali = convert_english_to_nepali(str(expire_date_english))
    

    try:
        bidded_prices = json.loads(quatation.bidded_prices)
    except (json.JSONDecodeError, AttributeError):
        bidded_prices = {}

    extracted_bids = []
    for firm_name, bids in bidded_prices.items():
        for bid in bids:
            for firm, price in bid.items():
                try:
                    suchikrit_firm = Suchikrit.objects.get(firm_name=firm)
                    firm_address = suchikrit_firm.firm_address
                    firm_owner = suchikrit_firm.firm_owner
                except Suchikrit.DoesNotExist:
                    firm_address = "Address not found"
                    firm_owner = "Owner not found"
                extracted_bids.append({
                    "firm_name": firm,
                    "bidded_price": price,
                    "firm_address": firm_address,
                    "firm_owner": firm_owner,
                })

    if extracted_bids:
        lowest_bid = min(extracted_bids, key=lambda x: x["bidded_price"])
        lowest_firm_name = lowest_bid["firm_name"]
        lowest_bidded_price = lowest_bid["bidded_price"]
        lowest_firm_address = lowest_bid["firm_address"]
        lowest_firm_onwer = lowest_bid["firm_owner"]
    else:
        lowest_firm_name = "N/A"
        lowest_bidded_price = "N/A"
        lowest_firm_address = "N/A"
        lowest_firm_onwer = "N/A"

    context = {
        "quatation": quatation,
        "extracted_bids": extracted_bids,
        "lowest_firm_name": lowest_firm_name,
        "lowest_bidded_price": lowest_bidded_price,
        "lowest_firm_address": lowest_firm_address,
        "lowest_firm_onwer": lowest_firm_onwer,
        "agreement_date_nepali":agreement_date_nepali,
        "expire_date_nepali":expire_date_nepali
        
    }

    return render(request, "Admin/Quatation/print_quatation_work_order.html", context) 


import json

def VIEW_QUATATION_ALL_PROJECTS(request):
    # Fetch all Quation objects with related Project data
    quations = Quation.objects.all().select_related('project').prefetch_related('suchikrit')

    # Prepare a list to hold the processed data
    processed_quations = []
    
    for quation in quations:
        # Parse the bidded_prices JSON field to find the lowest bidder
        lowest_bidder = None
        lowest_price = None
        
        # Check if the bidded_prices field is not empty and parse it
        if quation.bidded_prices:
            try:
                bidded_prices_data = json.loads(quation.bidded_prices)  # Parse the JSON string to a dictionary
                for project_name, bids in bidded_prices_data.items():
                    for bid in bids:
                        for firm_name, price in bid.items():
                            if lowest_price is None or price < lowest_price:
                                lowest_price = price
                                lowest_bidder = firm_name
            except json.JSONDecodeError:
                # Handle the error if bidded_prices is not a valid JSON string
                print("Error decoding bidded_prices field")

        # Create a dictionary to hold the quation data
        
        agreement_date_english = quation.agreement_date
        expire_date_english = quation.expire_date
        def convert_english_to_nepali(english_date_str):
            if english_date_str:
                english_year, english_month, english_day = map(int, english_date_str.split('-'))
                nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
                return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
                return None

    # Convert the start date from English to Nepali
        agreement_date = convert_english_to_nepali(str(agreement_date_english))
        expire_date = convert_english_to_nepali(str(expire_date_english))
        
        
        quation_data = {
            'id': quation.id,  # Include the ID field
            'project_name': quation.project.name,
            'budget': quation.project.budget,
            'cost_estimate': quation.cost_estimate,
            'contingency': quation.contingency,
            'firm_names': ', '.join(firm.firm_name for firm in quation.suchikrit.all()),  # Concatenate firm names
            'lowest_firm_name': lowest_bidder,  # Add the lowest bidder firm name
            'lowest_price': lowest_price  ,
            "agreement_date":agreement_date,
            "expire_date":expire_date
            
        }
        processed_quations.append(quation_data)

    context = {
        "quations": processed_quations  # Pass the processed data to the template
    }
    return render(request, "Admin/Quatation/view_quatation_all_project.html", context)




def ADD_QUATATION_FINAL_PAYMENT(request,id):
    quations = Quation.objects.all()
    
    context = {
        "quations":quations
    }
    return render(request,"Admin/Quatation/add_quatation_final_payment.html",context)

from django.http import JsonResponse

def get_cost_estimate(request):
    print("View triggered")  # Debugging
    quotation_id = request.GET.get('quotation_id')
    print("Quotation ID:", quotation_id)  # Debugging
    
    if quotation_id:
        try:
            quatation = Quation.objects.get(id=quotation_id)
            print("Quotation object:", quatation)  # Debugging
            return JsonResponse({'cost_estimate': quatation.cost_estimate}, status=200)
        except Quation.DoesNotExist:
            return JsonResponse({'error': 'Quotation not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)







def ADD_QUATATION_FINAL_PAYMENT_SIDEBAR(request):
    if request.method == "POST":
        quation_id = request.POST.get("id_project")
        print(f"Received quation_id: {quation_id}")

        if not quation_id:
            messages.error(request, "Quotation ID is missing.")
            return redirect('add_quatation_final_payment_sidebar')

        try:
            quation = Quation.objects.get(id=int(quation_id))  # Cast to int to ensure correct type
        except Quation.DoesNotExist:
            messages.error(request, "Quation not found.")
            return redirect('add_quatation_final_payment_sidebar')

        # Check if QuationFinal already exists for the same Quation
        if QuationFinal.objects.filter(quation=quation).exists():
            messages.warning(request, "Final already exists for the selected Quation.")
            return redirect('add_quatation_final_payment_sidebar')

        application_date_nepali = request.POST.get("application_date")
        totalValuation = request.POST.get("totalValuation")
        retension = request.POST.get("retension")
        taxdeduction = request.POST.get("taxdeduction")
        finalpayment = request.POST.get("finalpayment")

        def convert_nepali_to_english(nepali_date_str):
            if nepali_date_str:
                nepali_year, nepali_month, nepali_day = map(int, nepali_date_str.split('-'))
                english_year, english_month, english_day = converter.nepali_to_english(nepali_year, nepali_month, nepali_day)
                return f"{english_year}-{english_month:02d}-{english_day:02d}"
            return None

        # Convert Nepali dates to English dates
        application_date = convert_nepali_to_english(application_date_nepali)

        quationfinal = QuationFinal(
            quation=quation,
            application_date=application_date,
            totalValuation=totalValuation,
            retension=retension,
            taxdeduction=taxdeduction,
            finalpayment=finalpayment
        )
        quationfinal.save()

        messages.success(request, "Data added successfully.")
        return redirect('view_quatation_final_payment_sidebar')

    quatations = Quation.objects.all()

    context = {
        "quatations": quatations
    }
    return render(request, "Admin/Quatation/add_quatation_final_payment_sidebar.html", context)

def get_lowest_bidder(quation):
    if quation.bidded_prices:
        # Parse the bidded prices from JSON field
        bidded_prices = quation.bidded_prices
        lowest_bidder = None
        lowest_bid = float('inf')  # Start with an arbitrarily high value
        
        # Iterate through each bid
        for bid in bidded_prices:
            for firm_name, bid_amount in bid.items():
                if bid_amount < lowest_bid:
                    lowest_bid = bid_amount
                    lowest_bidder = firm_name
        
        return lowest_bidder, lowest_bid
    return None, None

import json
from django.shortcuts import render
def VIEW_QUATATION_FINAL_PAYMENT_SIDEBAR(request):
    quationfinal = QuationFinal.objects.select_related('quation__project').all()

    # Prepare data for template
    data = []
    for qfinal in quationfinal:
        quation = qfinal.quation
        try:
            # Parse the bidded_prices field as a Python dictionary
            bidded_prices = json.loads(quation.bidded_prices) if quation.bidded_prices else {}
            project_name = quation.project.name

            # Get bids for the specific project
            lowest_firm = None
            lowest_price = None
            if project_name in bidded_prices:
                bids = bidded_prices[project_name]
                # Find the lowest bid
                if bids:
                    lowest_bid = min(bids, key=lambda x: list(x.values())[0])
                    lowest_firm = list(lowest_bid.keys())[0]
                    lowest_price = list(lowest_bid.values())[0]

            # Append data for the template
            data.append({
                'id': qfinal.id,
                'project_name': project_name,
                'cost_estimate': quation.cost_estimate,
                'contingency': quation.contingency,
                'agreement_date': quation.agreement_date,
                'expire_date': quation.expire_date,
                'firm_name': ", ".join([firm.firm_name for firm in quation.suchikrit.all()]),
                'lowest_bidder_firm': lowest_firm,
                'lowest_bidded_price': lowest_price,
                'final_payment': qfinal.finalpayment,
                'total_valuation': qfinal.totalValuation,
                'retention': qfinal.retension,
                'tax_deduction': qfinal.taxdeduction,
            })
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Handle invalid JSON or missing project data gracefully
            print(f"Error processing bidded_prices for quation {quation}: {e}")
            continue

    context = {
        'data': data,
    }
    return render(request, 'Admin/Quatation/view_quatation_final_payment_sidebar.html', context)



def PRINT_QUATATION_FINAL_PAYMENT_TIPPANI(request, id):
    try:
        # Get the specific QuationFinal object using the ID
        qfinal = QuationFinal.objects.select_related('quation__project').get(id=id)
        quation = qfinal.quation
        
        agreement_date_english  =quation.agreement_date
        def convert_english_to_nepali(english_date_str):
            if english_date_str:
                english_year, english_month, english_day = map(int, english_date_str.split('-'))
                nepali_year, nepali_month, nepali_day = converter.english_to_nepali(english_year, english_month, english_day)
                return f"{nepali_year}-{nepali_month:02d}-{nepali_day:02d}"
            return None

    # Convert the start date from English to Nepali
        start_date_nepali = convert_english_to_nepali(str(agreement_date_english))
        

        # Parse bidded_prices field as a Python dictionary
        bidded_prices = json.loads(quation.bidded_prices) if quation.bidded_prices else {}
        project_name = quation.project.name

        # Get bids for the specific project
        lowest_firm = None
        lowest_price = None
        if project_name in bidded_prices:
            bids = bidded_prices[project_name]
            # Find the lowest bid
            if bids:
                lowest_bid = min(bids, key=lambda x: list(x.values())[0])
                lowest_firm = list(lowest_bid.keys())[0]
                lowest_price = list(lowest_bid.values())[0]

        # स्वीकृत (न्यूनतम) फर्मको ठेगाना मात्र
        winner = quation.suchikrit.filter(firm_name=lowest_firm).first() if lowest_firm else None
        firm_addresses = winner.firm_address if winner else ""

        # Prepare data for the template
        data = {
            'id': qfinal.id,
            'fiscalyear':quation.project.fiscalyear.name,
            'project_name': project_name,
            'cost_estimate': quation.cost_estimate,
            'contingency': quation.contingency,
            'start_date_nepali': start_date_nepali,
            'expire_date': quation.expire_date,
            'firm_name': ", ".join([firm.firm_name for firm in quation.suchikrit.all()]),
            'firm_address': firm_addresses,  # Adding firm address here
            'lowest_bidder_firm': lowest_firm,
            'lowest_bidded_price': lowest_price,
            'final_payment': qfinal.finalpayment,
            'total_valuation': qfinal.totalValuation,
            'retention': qfinal.retension,
            'tax_deduction': qfinal.taxdeduction,
            'advance': qfinal.advance_deducted or 0,
            'ward':quation.project.ward.name
        }

        # Pass data to the template
        context = {
            'data': data,
        }
        return render(request, "Admin/Quatation/print_quatation_final_payment_tippani.html", context)
    except QuationFinal.DoesNotExist:
        return HttpResponse("QuationFinal object not found.", status=404)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        return HttpResponse(f"Error processing data: {e}", status=500)






def VIEW_ESTIMATED_PROJECT(request):
    
    cost_estimate = CostEstimate.objects.all().order_by('-id')
    context = {
      
        "cost_estimate":cost_estimate
    }
    
    return render(request,"Admin/User/view_estimated_project.html",context)


def PRINT_QUATATION_ADVANCE_TIPPANI(request, id):
    """दरभाउपत्र: अग्रिम भुक्तानी स्वीकृत गर्ने टिप्पणी (बैंक जमानत सहित)."""
    import datetime

    from usercommittee.workflow import bs_date

    from .models import QuationAdvance
    from .workflow import lowest

    advance = get_object_or_404(QuationAdvance.objects.select_related("quation__project"), id=id)
    quation = advance.quation
    firm_name, price = lowest(quation)
    firm = quation.suchikrit.filter(firm_name=firm_name).first() if firm_name else None
    return render(request, "Admin/Quatation/print_quatation_advance_tippani.html", {
        "advance": advance, "quatation": quation, "project": quation.project,
        "firm_name": firm_name, "firm_address": firm.firm_address if firm else "", "agreed_amount": price,
        "today_nepali": bs_date(datetime.date.today()),
        "agreement_date_nepali": bs_date(quation.agreement_date),
        "approval_date_nepali": bs_date(advance.approval_date),
        "issue_date_nepali": bs_date(advance.issue_date),
        "expiry_date_nepali": bs_date(advance.expiry_date),
    })
