"""/media/ — DEBUG बन्द भए पनि (cPanel/Passenger) Django ले नै दिन्छ, तर पालिकाअनुसार सुरक्षित:

  * media/palika_logos/...        — लोगो, पत्र शीर्ष (सबैले हेर्न मिल्ने; login पेजमा पनि चाहिन्छ)
  * media/<यही पालिकाको schema>/... — यही पालिकाका कागजात (login चाहिन्छ — middleware ले जाँच्छ)
  * media/<schema>/persons/...     — कहिल्यै सिधै होइन; /UserCommittee/Person/<id>/doc/<kind>/ (अनुमति जाँचेर)
  * अर्को पालिकाको फोल्डर वा अरू जुनसुकै — 404
"""
import posixpath

from django.conf import settings
from django.db import connection
from django.http import Http404
from django.views.static import serve

PUBLIC_PREFIXES = ("palika_logos",)


def allowed(path, schema):
    path = posixpath.normpath(path).lstrip("/")
    if path.startswith("..") or "/../" in f"/{path}/":
        return False
    parts = path.split("/")
    if len(parts) < 2:
        return False
    if parts[0] in PUBLIC_PREFIXES:
        return True
    if schema and schema != "public" and parts[0] == schema:
        return parts[1] != "persons"
    return False


def tenant_media(request, path):
    if not allowed(path, getattr(connection, "schema_name", "public")):
        raise Http404
    return serve(request, path, document_root=settings.MEDIA_ROOT)
