from django.urls import path
from .import views
from . import views_workflow, views_installments, views_audit, views_reports
from .models import DocumentPrint
from .workflow import logs_print, uc_gate

urlpatterns = [
    # ================= कार्यप्रवाह (workflow tracker) =================
    path('Reports/', views_reports.summary, name='uc_report_summary'),
    path('Reports/Projects/', views_reports.projects, name='uc_report_projects'),
    path('Reports/Taxes/', views_reports.taxes, name='uc_report_taxes'),
    path('Workflow/', views_workflow.workflow_list, name='usercommittee_workflow'),
    path('Workflow/<int:project_id>/', views_workflow.workflow_detail, name='usercommittee_workflow_detail'),
    path('Workflow/<int:project_id>/approve/', views_workflow.approve, name='uc_approve'),
    path('Workflow/<int:project_id>/sifaris/<str:kind>/', views_workflow.sifaris_upload, name='uc_sifaris_upload'),
    path('Workflow/Approvers/', views_workflow.approvers, name='uc_approvers'),
    path('Workflow/<int:project_id>/committee/', views_workflow.committee_review, name='uc_committee_review'),
    path('Person/<int:person_id>/doc/<str:kind>/', views_workflow.person_doc, name='uc_person_doc'),

    path('add/', views.add_usercommittee, name='add_usercommittee'),
    path('add/<int:project_id>/', views.add_usercommittee, name='add_usercommittee_for_project'),
    path('nid-lookup/', views.nid_lookup, name='uc_nid_lookup'),
    path('tax-heads/', views.tax_heads_page, name='tax_heads'),
    path('Workflow/<int:project_id>/bank-account/', views_installments.bank_account, name='uc_bank_account'),
    path('Workflow/<int:project_id>/installments/', views_installments.installments, name='uc_installments'),
    path('Workflow/<int:project_id>/installments/<int:inst_id>/', views_installments.installments, name='uc_installment_edit'),
    path('Print/Installment/<int:inst_id>/', views_installments.print_installment, name='uc_print_installment'),
    path('Workflow/<int:project_id>/public-audit/', views_audit.public_audit, name='uc_public_audit'),
    path('Print/PublicAudit/<int:project_id>/', views_audit.print_public_audit, name='uc_print_public_audit'),
    path('tax-heads/add/', views.tax_head_add_ajax, name='tax_head_add'),
    path('add-cost-estimate/', views.add_cost_estimate, name='add_cost_estimate'),
    path('add-cost-estimate/<int:project_id>/', views.add_cost_estimate, name='add_cost_estimate_for_project'),
    path('view-estimated-projects/', views.view_estimated_projects, name='view_estimated_projects'),
    path('Print/Contract/Document/<str:id>/', uc_gate(logs_print(views.PRINT_CONTRACT_DOCUMENT, DocumentPrint.CONTRACT), 'agreement'), name='print_documents'), 
    path('Print/Tippani/Document/<str:id>/', uc_gate(logs_print(views.PRINT_TIPPANI, DocumentPrint.TIPPANI), 'agreement'), name='print_tippani'), 
    path('Print/Bank/Letter/<str:id>/', uc_gate(logs_print(views.PRINT_BANK_LETTER, DocumentPrint.BANK_LETTER), 'agreement'), name='print_bank_letter'), 
    path('Print/Work/Order/<str:id>/', uc_gate(logs_print(views.PRINT_WORK_ORDER, DocumentPrint.WORK_ORDER), 'agreement'), name='print_work_order'), 
    path('add-final-valuation/', views.add_final_valuation, name='add_final_valuation'),
    path('edit-final-valuation/<int:id>/', views.edit_final_valuation, name='edit_final_valuation'),
    path('ajax/load-user-contribtuion/', views.LOAD_USER_CONTRIBUTION, name = "ajax_load_user_contribution"),
    path('ajax/load-contingency/', views.LOAD_CONTINGENCY, name = "ajax_load_contingency"),
    path('ajax/load-budget/', views.LOAD_BUDGET, name = "ajax_load_budget"),
    path('Final/Valuation/', views.VIEW_FINAL_VALUATION,name='view_final_valuation'),
    path('Print/Final/Tippani/<str:id>/', uc_gate(logs_print(views.PRINT_FINAL_TIPPANI, DocumentPrint.FINAL_TIPPANI), 'final_tippani'), name='usercommittee_print_final_tippani'),
    path('Print/Handover/Letter/<str:id>', uc_gate(logs_print(views.PRINT_HANDOVER_LETTER, DocumentPrint.HANDOVER), 'handover'),name='print_handover_letter'),
    path('view-usercommittee/', views.view_usercommittee, name='view_usercommittee'),
    path('edit-usercommittee/<str:id>/', views.edit_usercommittee, name='edit_usercommittee'),
    path('extend-usercommittee-date/<str:id>/', views.extend_usercommittee_date, name='extend_usercommittee_date'),      
    path('update-usercommittee/', views.update_usercommittee, name='update_usercommittee'),
    path('update-usercommittee-date/', views.update_usercommittee_date, name='update_usercommittee_date'),
    path('print-extended-letter/<str:id>/', views.PRINT_EXTENDED_LETTER, name='print_extended_usercommittee_date'),
    path('view_usercommittee_payments/', views.view_usercommittee_payments, name='view_usercommittee_payments'),
    path('usercommittee-payments/download/',views.download_usercommittee_payments_excel,name='download_usercommittee_payments_excel'
),

    # ================= वडा सचिव सिफारिस =================
    path('WardSachib/Projects/All/', views.ward_project_list, name='ward_project_list'),
    path('WardSachib/Projects/', views.view_projects_for_recommendation, name='view_projects_for_recommendation'),
    path('WardSachib/Add/Recommendation/<int:id>/', views.add_ward_recommendation, name='add_ward_recommendation'),
    path('WardSachib/Print/Recommendation/<int:id>/', views.print_ward_recommendation, name='print_ward_recommendation'),

    # ================= वडा सचिव काम सम्पन्न सिफारिस =================
    path('WardSachib/Completion/Projects/', views.view_projects_for_completion_recommendation, name='view_projects_for_completion_recommendation'),
    path('WardSachib/Add/CompletionRecommendation/<int:id>/', views.add_completion_recommendation, name='add_completion_recommendation'),
    path('WardSachib/Print/CompletionRecommendation/<int:id>/', views.print_completion_recommendation, name='print_completion_recommendation'),

    # ================= वडा इन्जिनियर लागत अनुमान =================
    path('WardEngineer/Projects/All/', views.ward_engineer_project_list, name='ward_engineer_project_list'),
    path('WardEngineer/Project/<int:project_id>/Photos/', views.ward_engineer_project_photos, name='ward_engineer_project_photos'),

    # ================= पालिका इन्जिनियर लागत अनुमान (सबै वडा) =================
    path('PalikaEngineer/Projects/All/', views.palika_engineer_project_list, name='palika_engineer_project_list'),
    path('PalikaEngineer/EditCostEstimate/<int:id>/', views.edit_cost_estimate, name='edit_cost_estimate'),

    # ================= पालिका इन्जिनियर — थप पृष्ठहरू =================
    path('PalikaEngineer/Project/<int:id>/', views.palika_engineer_project_detail, name='palika_engineer_project_detail'),
    path('PalikaEngineer/Project/<int:project_id>/AddInspectionNote/', views.add_site_inspection_note, name='add_site_inspection_note'),
    path('PalikaEngineer/EstimatedProjects/', views.palika_engineer_estimated_projects, name='palika_engineer_estimated_projects'),
    path('PalikaEngineer/EstimatedProjects/Download/', views.download_palika_engineer_estimated_projects_excel, name='download_palika_engineer_estimated_projects_excel'),
    path('PalikaEngineer/WardComparison/', views.palika_engineer_ward_comparison, name='palika_engineer_ward_comparison'),
    path('PalikaEngineer/Committees/', views.palika_engineer_committee_list, name='palika_engineer_committee_list'),
    path('PalikaEngineer/FinalValuations/', views.palika_engineer_final_valuations, name='palika_engineer_final_valuations'),
    path('PalikaEngineer/CommitteeReport/', views.palika_engineer_committee_financial_report, name='palika_engineer_committee_financial_report'),
    path('PalikaEngineer/CommitteeReport/Download/', views.download_committee_financial_report_excel, name='download_committee_financial_report_excel'),

    # ================= परिवर्तन लग (Admin मात्र) =================
    path('ActivityLog/', views.activity_log, name='activity_log'),

]