from django.urls import path
from .import views
from . import views_roles
from . import views_office
from . import views_wards
from . import views_mywork
from . import views_password
from . import views_search

urlpatterns = [
    path('MyWork/', views_mywork.my_work_page, name='my_work'),
    path('MyWork/panel/', views_mywork.my_work_panel, name='my_work_panel'),
    path('MyWork/badge/', views_mywork.my_work_badge, name='my_work_badge'),
    path('MyWork/next/', views_mywork.my_work_next, name='my_work_next'),
    path('Search/', views_search.global_search, name='global_search'),
    path('login/', views.login_view, name='login'),
    path('doLogin/', views.doLogin, name='doLogin'),
    path('doLogout', views.doLogout, name='logout'),
    path('forgot-password/', views_password.forgot, name='forgot_password'),
    path('forgot-password/verify/', views_password.verify, name='forgot_password_verify'),
    path('Admin/Home/', views.ADMIN_HOME, name='admin_home'),
    path('Admin/Add/Staff/', views.add_staff, name='add_staff'),
    path('Admin/ManageStaff/', views.manage_staff, name='manage_staff'),
    path('Admin/Roles/', views_roles.roles_permissions, name='roles_permissions'),
    path('Admin/Office/', views_office.office_settings, name='office_settings'),
    path('Admin/Wards/', views_wards.manage_wards, name='manage_wards'),
    path('Admin/ResetPassword/<int:user_id>/', views.reset_staff_password, name='reset_staff_password'),
    path('Engineer/Home/', views.engineer_home, name='engineer_home'),
    path('Engineer/View/Projects', views.view_projects_engineer, name='view_projects_engineer'),
    path('Engineer/View/UserCommittee', views.view_usercommittee_engineer, name='view_usercommittee_engineer'),
    path('Engineer/View/AdvanceBankGuarantees', views.view_advance_bank_guarantees_engineer, name='view_advance_bank_guarantees_engineer'),
    path('Engineer/View/PerformanceBankGuarantees', views.view_performance_bank_guarantees_engineer, name='view_performance_bank_guarantees_engineer'),
    path('unauthorized/', views.unauthorized_view, name='unauthorized'),
    path('WardSachib/Home/', views.ward_sachib_home, name='ward_sachib_home'),
    path('Planning/Home/', views.planning_home, name='planning_home'),
    path('WardEngineer/Home/', views.ward_engineer_home, name='ward_engineer_home'),
    path('PalikaEngineer/Home/', views.palika_engineer_home, name='palika_engineer_home'),
]