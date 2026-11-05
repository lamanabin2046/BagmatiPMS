from django.urls import path

from . import views

urlpatterns = [
    path("save/", views.save, name="letter_save"),
    path("reset/", views.reset, name="letter_reset"),
    path("templates/", views.templates_list, name="letter_templates"),
]
