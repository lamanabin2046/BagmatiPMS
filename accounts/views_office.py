"""कार्यालय सेटिङ — पालिकाको Admin ले आफ्नै पत्र शीर्ष, लोगो, नारा, वेबसाइट, इमेल मिलाउने पेज."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .permissions import has_perm


@login_required
def office_settings(request):
    from tenants.forms import OfficeSettingsForm
    from tenants.models import Palika

    if not has_perm(request.user, "settings.office"):
        return redirect("unauthorized")
    tenant = getattr(request, "tenant", None)
    palika = Palika.objects.filter(pk=getattr(tenant, "pk", None)).first()
    if palika is None:
        return redirect("unauthorized")

    if request.method == "POST":
        form = OfficeSettingsForm(request.POST, request.FILES, instance=palika)
        if form.is_valid():
            obj = form.save(commit=False)
            for field in ("logo", "letterhead_image"):
                if request.POST.get(f"remove_{field}") and not request.FILES.get(field):
                    f = getattr(palika, field)
                    if f:
                        f.delete(save=False)
                    setattr(obj, field, None)
            obj.save()
            messages.success(request, "कार्यालय सेटिङ सुरक्षित भयो। अब सबै पत्रमा नयाँ पत्र शीर्ष देखिन्छ।")
            return redirect("office_settings")
    else:
        form = OfficeSettingsForm(instance=palika)
    return render(request, "Admin/Accounts/office_settings.html", {"form": form, "palika": palika})
