from django.http import HttpResponse


class InactivePalikaMiddleware:
    """Block a palika's site while it is disabled in the SaaS manager (e.g. unpaid)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is not None and tenant.schema_name != "public" and not getattr(tenant, "is_active", True):
            return HttpResponse(
                "<div style='font-family:sans-serif;text-align:center;margin-top:15vh'>"
                "<h2>यो पालिकाको सेवा हाल निष्क्रिय छ।</h2>"
                "<p>This palika's account is currently inactive. Please contact the service provider.</p></div>",
                status=403,
            )
        return self.get_response(request)


class PalikaLoginRequiredMiddleware:
    """Every page of a palika site requires login (the old views mostly had no check).

    Only the login pages and Django admin (which has its own login) are open.
    """

    OPEN_PREFIXES = ("/Accounts/login/", "/Accounts/doLogin/", "/Accounts/forgot-password/", "/admin/", "/static/", "/media/palika_logos/", "/favicon.ico",
                     "/Projects/Public/")   # राजस्व ठेक्काको सार्वजनिक सूचना र अनलाइन बोलपत्र (projects/revenue_portal.py)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if (
            tenant is not None
            and tenant.schema_name != "public"
            and not request.user.is_authenticated
            and request.path != "/"
            and not request.path.startswith(self.OPEN_PREFIXES)
        ):
            from django.shortcuts import redirect

            return redirect("/Accounts/login/")
        return self.get_response(request)
