from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path
from django.views.generic import RedirectView

from . import views, views_workflow as wf
from .workflow import quot_print


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


manage, view = need("quot.manage"), need("quot.view")

urlpatterns = [
    # ================= कार्यप्रवाह (workflow) =================
    path('Workflow/', wf.workflow_list, name='quot_workflow'),
    path('Workflow/<int:project_id>/', wf.workflow_detail, name='quot_workflow_detail'),
    path('Workflow/<int:project_id>/invite/', wf.invite, name='quot_wf_invite'),
    path('Workflow/<int:project_id>/quotes/', wf.quotes, name='quot_wf_quotes'),
    path('Workflow/<int:project_id>/approve/', wf.approve, name='quot_wf_approve'),
    path('Workflow/<int:project_id>/agreement/', wf.agreement, name='quot_wf_agreement'),
    path('Workflow/<int:project_id>/final/', wf.final, name='quot_wf_final'),
    path('Workflow/<int:project_id>/advance/', wf.advance, name='quot_wf_advance'),
    path('Advance/Guarantees/', RedirectView.as_view(url='/Projects/Guarantees/Advance/?kind=quot'), name='quot_advance_guarantees'),

    # ================= छाप्ने (अनुमति + क्रम जाँच, छापिएको अभिलेख, कार्यप्रवाहमा फर्कने) =================
    path('Print/Quatation/<str:id>', quot_print(views.PRINT_QUATATION_TIPPANI, "invite_tippani", "q"), name='print_quatation_tippani'),
    path('Send/Letter/<str:id>', quot_print(views.SEND_QUATATION_LETTER, "invite_letter", "q"), name='send_quatation_letter'),
    path('Approved/Tippani/<str:id>', quot_print(views.APPROVED_QUATATION_TIPPANI, "approval_tippani", "q"), name='approved_quatation_tippani'),
    path('Print/Agreement/<str:id>', quot_print(views.PRINT_QUATATION_AGREEMENT, "agreement", "q"), name='print_quatation_agreement'),
    path('Print/Work/Order/<str:id>', quot_print(views.PRINT_QUATATION_WORK_ORDE, "work_order", "q"), name='print_quatation_work_order'),
    path('Print/Advance/Tippani/<int:id>', quot_print(views.PRINT_QUATATION_ADVANCE_TIPPANI, None, "advance"),
         name='print_quatation_advance_tippani'),
    path('Print/Final/Payments/Tippani/<str:id>', quot_print(views.PRINT_QUATATION_FINAL_PAYMENT_TIPPANI, "final_tippani", "final"),
         name='print_quatation_final_payment_tippani'),

    # ================= सूचीकृत फर्म =================
    # सूचीकृत फर्म — अब फर्म / निर्माण व्यवसायी दर्ता (एउटै सूची)
    path('Add/Suchi/add_suchikrit_list', RedirectView.as_view(url='/Projects/Firms/'), name='add_suchikrit_list'),
    path('View/Suchi/view_suchikrit_list', RedirectView.as_view(url='/Projects/Firms/?status=enlisted'), name='view_suchikrit_list'),

    # ================= पुराना फारम / सूची (अब कार्यप्रवाहबाटै गर्न सकिन्छ) =================
    path('Invite/Quation', manage(views.INVITE_QUATATION), name='invite_quatation'),
    path('Invite/Quatation/Project', view(views.VIEW_QUATATION_PROJECTS), name='view_quatation_projects'),
    path('View/All/Project', view(views.VIEW_QUATATION_ALL_PROJECTS), name='view_quatation_all_projects'),
    path('Add/Quatation/Amount/<str:id>', manage(views.ADD_QUATATION_AMOUNT), name='add_quatation_amount'),
    path('Add/Agreement/<str:id>', manage(views.ADD_QUATATION_AGREEMENT), name='add_quatation_agreement'),
    path('Add/Final/Payment/<str:id>', manage(views.ADD_QUATATION_FINAL_PAYMENT), name='add_quatation_final_payment'),
    path('Add/Final/Payments/', manage(views.ADD_QUATATION_FINAL_PAYMENT_SIDEBAR), name='add_quatation_final_payment_sidebar'),
    path('View/Final/Payments/', view(views.VIEW_QUATATION_FINAL_PAYMENT_SIDEBAR), name='view_quatation_final_payment_sidebar'),
]
