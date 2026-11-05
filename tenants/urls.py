from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="saas_dashboard"),
    path("login/", views.saas_login, name="saas_login"),
    path("logout/", views.saas_logout, name="saas_logout"),
    path("palika/new/", views.palika_create, name="saas_palika_create"),
    path("palika/<int:pk>/", views.palika_detail, name="saas_palika_detail"),
    path("palika/<int:pk>/edit/", views.palika_edit, name="saas_palika_edit"),
    path("palika/<int:pk>/toggle/", views.palika_toggle, name="saas_palika_toggle"),
    path("palika/<int:pk>/reset-password/", views.admin_reset_password, name="saas_admin_reset_password"),
    path("palika/<int:pk>/domain/add/", views.domain_add, name="saas_domain_add"),
    path("palika/<int:pk>/wards/", views.palika_wards, name="saas_palika_wards"),
    path("palika/<int:pk>/domain/<int:domain_id>/delete/", views.domain_delete, name="saas_domain_delete"),
]
