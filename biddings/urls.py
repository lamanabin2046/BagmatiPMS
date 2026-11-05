from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path
from django.views.generic import RedirectView

from . import views, views_workflow as wf
from .workflow import bid_print


def need(perm):
    """पुराना (मेनुका) पेजमा पनि अनुमति जाँच."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            from accounts.permissions import has_perm

            if not has_perm(request.user, perm):
                messages.error(request, "यो पेज हेर्ने अनुमति तपाईंलाई छैन।")
                return redirect("unauthorized")
            return view(request, *args, **kwargs)
        return wrapper
    return deco


manage, view = need("bid.manage"), need("bid.view")

urlpatterns = [
   # ================= कार्यप्रवाह (workflow) =================
   path('Workflow/', wf.workflow_list, name='bid_workflow'),
   path('Workflow/<int:project_id>/', wf.workflow_detail, name='bid_workflow_detail'),
   path('Workflow/<int:project_id>/notice/', wf.notice, name='bid_wf_notice'),
   path('Workflow/<int:project_id>/evaluation/', wf.evaluation, name='bid_wf_evaluation'),
   path('Workflow/<int:project_id>/approve/', wf.approve, name='bid_wf_approve'),
   path('Workflow/<int:project_id>/acceptance/', wf.acceptance, name='bid_wf_acceptance'),
   path('Workflow/<int:project_id>/agreement/', wf.agreement, name='bid_wf_agreement'),
   path('Workflow/<int:project_id>/advance/', wf.advance, name='bid_wf_advance'),
   path('Workflow/<int:project_id>/extension/', wf.extension, name='bid_wf_extension'),
   path('Workflow/<int:project_id>/variation/', wf.variation, name='bid_wf_variation'),
   path('Workflow/<int:project_id>/running/', wf.running, name='bid_wf_running'),
   path('Workflow/<int:project_id>/final/', wf.final, name='bid_wf_final'),

   # ================= छाप्ने (अनुमति + क्रम जाँच, छापिएको अभिलेख) =================
   path('print_asay_notice/<int:id>/', bid_print(views.print_asay_notice, "asay", "bid"), name='print_asay_notice'),
   path('print_contract_tippani/<int:id>/', bid_print(views.print_contract_tippani, "tippani", "bid"), name='print_contract_tippani'),
   path('print_contract_invite/<int:id>/', bid_print(views.print_contract_invite, "invite", "bid"), name='print_contract_invite'),
   path('print_contract_paper/<int:id>/', bid_print(views.print_contract_paper, "contract", "bond"), name='print_contract_paper'),
   path('print_bid_work_order/<int:id>/', bid_print(views.print_bid_work_order, "work_order", "bond"), name='print_bid_work_order'),
   path('print_advance_tippani/<int:id>/', bid_print(views.print_advance_tippani, None, "advance"), name='print_advance_tippani'),
   path("print_running_tippani/<int:id>/", bid_print(views.print_running_tippani, None, "running"), name="print_running_tippani"),
   path('print_final_tippani/<int:id>/', bid_print(views.print_final_tippani, "final_tippani", "final"), name='print_final_tippani'),
   path("print_performance_bond_tippani/<int:id>/", bid_print(views.print_performance_bond_tippani, None, "bond"),
        name="print_performance_bond_tippani"),

   # ================= पुराना फारम (मेनुबाट; अब कार्यप्रवाहबाटै गर्न सकिन्छ) =================
   path('Project/Bid/Detail', manage(views.ADD_BID_DETAIL), name='add_bid_detail'),
   path('add_pg_requirement/<int:id>/', manage(views.ADD_PG_REQUIREMENT), name='add_pg_requirement'),
   path('add_pg_bank_detail/<int:bidding_id>/', manage(views.add_pg_bank_detail), name='add_pg_bank_detail'),
   path('Project/Advance/Payment/Add', manage(views.add_advance_payment), name='add_advance_payment'),
   path("get-sealed-bid-contract-info/<int:sealed_bid_id>/", view(views.get_sealed_bid_contract_info),
        name="get_sealed_bid_contract_info"),
   # पुरानो म्याद थप पेज → कार्यप्रवाहको म्याद थप (कारण, निवेदन मिति, हर्जाना सहित/बिना, निर्णय)
   path("performance-bond/extend/<int:id>/", manage(views.extend_performance_bond), name="extend_performance_bond"),
   path("performance-bond/extend/update/", manage(views.update_performance_bond_expiry), name="update_performance_bond_expiry"),
   path('Project/Final/Payment/Add', manage(views.add_final_payment), name='add_final_payment'),
   path("running-evaluation/add/", manage(views.add_running_evaluation), name="add_running_evaluation"),

   # ================= सूची / प्रतिवेदन =================
   path('View/Bid/Detail', view(views.VIEW_BID_DETAIL), name='view_bid_detail'),
   path('view_approved_projects', view(views.view_approved_projects), name='view_approved_projects'),
   path('Project/View/Agreement/Projects', view(views.view_agreement_projects), name='view_agreement_projects'),
   # पुराना जमानत सूची → बैंक ग्यारेन्टी मेनु
   path('view_performance_bank_guarantees', RedirectView.as_view(pattern_name='performance_guarantees', query_string=True),
        name='view_performance_bank_guarantees'),
   path('view_advance_bank_guarantees', RedirectView.as_view(url='/Projects/Guarantees/Advance/?kind=bid'),
        name='view_advance_bank_guarantees'),
   path('view_advance_payment', view(views.view_advance_payment), name='view_advance_payment'),
   path('view_running_evaluations', view(views.view_running_evaluations), name='view_running_evaluations'),
   path("final-payments/", view(views.view_final_payment), name="view_final_payment"),
]
