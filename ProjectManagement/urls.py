# vehicleManagement/urls.py

from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('Accounts/', include('accounts.urls')),
    path('Projects/', include('projects.urls')),
    path('UserCommittee/', include('usercommittee.urls')),
    path('Bidding/', include('biddings.urls')),
    path('Quatation/', include('quatation.urls')),
    path('Letters/', include('letters.urls')),
    path('', RedirectView.as_view(url='/Accounts/login/', permanent=False)),
]


# /media/ — DEBUG होस् वा नहोस्, पालिकाअनुसार सुरक्षित (ProjectManagement/media.py)
from django.urls import re_path

from .media import tenant_media

urlpatterns += [re_path(r"^media/(?P<path>.+)$", tenant_media)]
