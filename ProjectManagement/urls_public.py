"""URLs for BASE_DOMAIN (public schema): the SaaS manager."""
from django.contrib import admin
from django.urls import include, path, re_path

from .media import tenant_media

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("tenants.urls")),
]

# पालिकाको लोगो आदि (media/palika_logos/) — DEBUG बन्द भए पनि
urlpatterns += [re_path(r"^media/(?P<path>.+)$", tenant_media)]
