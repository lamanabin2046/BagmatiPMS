"""SaaS manager (runs only on BASE_DOMAIN, the public schema)."""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_tenants.utils import schema_context

from .forms import DomainForm, PalikaCreateForm, PalikaUpdateForm
from .models import Domain, Palika
from .provisioning import create_palika, provision_palika, reset_admin_password


def saas_staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("saas_login")
        if not request.user.is_superuser:
            logout(request)
            messages.error(request, "SaaS manager मा पहुँच छैन।")
            return redirect("saas_login")
        return view(request, *args, **kwargs)

    return wrapper


def port_suffix(request):
    host = request.get_host()
    return ":" + host.split(":", 1)[1] if ":" in host else ""


def saas_login(request):
    if request.method == "POST":
        user = authenticate(request, mobile=request.POST.get("mobile", "").strip(),
                            password=request.POST.get("password", ""))
        if user is not None and user.is_superuser:
            login(request, user)
            return redirect("saas_dashboard")
        messages.error(request, "मोबाइल नम्बर वा पासवर्ड गलत छ।")
    return render(request, "saas/login.html")


def saas_logout(request):
    logout(request)
    return redirect("saas_login")


def palikas():
    return Palika.objects.exclude(schema_name="public")


def palika_stats(palika):
    """Counts read from inside the palika's own schema."""
    from accounts.models import CustomUser
    from projects.models import Project

    from accounts.models import Ward
    from accounts.wards import sorted_wards

    try:
        with schema_context(palika.schema_name):
            wards = [w.name for w in sorted_wards()]
            return {"projects": Project.objects.count(), "users": CustomUser.objects.count(),
                    "wards": len(wards), "ward_names": wards}
    except Exception:
        return {"projects": "-", "users": "-", "wards": "-", "ward_names": []}


@saas_staff_required
def dashboard(request):
    rows = [(p, palika_stats(p)) for p in palikas().prefetch_related("domains")]
    ctx = {
        "rows": rows,
        "total": len(rows),
        "active": sum(1 for p, _ in rows if p.is_active),
        "port": port_suffix(request),
    }
    return render(request, "saas/dashboard.html", ctx)


@saas_staff_required
def palika_create(request):
    form = PalikaCreateForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        fields = {k: data[k] for k in PalikaCreateForm.Meta.fields if k != "name"}
        palika = create_palika(
            schema_name=data["schema_name"], name=data["name"],
            base_domain=settings.BASE_DOMAIN, **fields,
        )
        password = provision_palika(
            palika, admin_mobile=data["admin_mobile"], admin_name=data["admin_name"],
            admin_password=data.get("admin_password") or None,
            number_of_wards=data.get("number_of_wards") or 0,
        )
        request.session["new_credentials"] = {
            "palika": palika.full_name,
            "url": f"http://{palika.primary_domain}{port_suffix(request)}/",
            "mobile": data["admin_mobile"],
            "password": password,
        }
        return redirect("saas_palika_detail", pk=palika.pk)
    return render(request, "saas/palika_form.html", {"form": form, "creating": True,
                                                     "base_domain": settings.BASE_DOMAIN})


@saas_staff_required
def palika_detail(request, pk):
    palika = get_object_or_404(palikas(), pk=pk)
    from accounts.models import CustomUser

    with schema_context(palika.schema_name):
        admins = list(CustomUser.objects.filter(user_type="1").values("id", "mobile", "first_name", "is_active"))
    ctx = {
        "palika": palika,
        "stats": palika_stats(palika),
        "admins": admins,
        "domains": palika.domains.all(),
        "domain_form": DomainForm(),
        "credentials": request.session.pop("new_credentials", None),
        "port": port_suffix(request),
    }
    return render(request, "saas/palika_detail.html", ctx)


@saas_staff_required
def palika_edit(request, pk):
    palika = get_object_or_404(palikas(), pk=pk)
    form = PalikaUpdateForm(request.POST or None, request.FILES or None, instance=palika)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "पालिकाको विवरण सुरक्षित भयो।")
        return redirect("saas_palika_detail", pk=pk)
    return render(request, "saas/palika_form.html", {"form": form, "creating": False, "palika": palika})


@saas_staff_required
@require_POST
def palika_toggle(request, pk):
    palika = get_object_or_404(palikas(), pk=pk)
    palika.is_active = not palika.is_active
    palika.save(update_fields=["is_active"])
    messages.success(request, f"{palika.full_name}: {'सक्रिय' if palika.is_active else 'निष्क्रिय'} गरियो।")
    return redirect("saas_palika_detail", pk=pk)


@saas_staff_required
@require_POST
def admin_reset_password(request, pk):
    palika = get_object_or_404(palikas(), pk=pk)
    mobile = request.POST.get("mobile", "")
    try:
        password = reset_admin_password(palika, mobile)
    except Exception:
        messages.error(request, "प्रयोगकर्ता भेटिएन।")
        return redirect("saas_palika_detail", pk=pk)
    request.session["new_credentials"] = {
        "palika": palika.full_name,
        "url": f"http://{palika.primary_domain}{port_suffix(request)}/",
        "mobile": mobile, "password": password,
    }
    return redirect("saas_palika_detail", pk=pk)


@saas_staff_required
@require_POST
def domain_add(request, pk):
    palika = get_object_or_404(palikas(), pk=pk)
    form = DomainForm(request.POST)
    if form.is_valid():
        Domain.objects.create(domain=form.cleaned_data["domain"], tenant=palika, is_primary=False)
        messages.success(request, "डोमेन थपियो। DNS लाई यो server तर्फ point गर्नुहोस्।")
    else:
        messages.error(request, "; ".join(form.errors.get("domain", ["गलत डोमेन"])))
    return redirect("saas_palika_detail", pk=pk)


@saas_staff_required
@require_POST
def domain_delete(request, pk, domain_id):
    palika = get_object_or_404(palikas(), pk=pk)
    d = get_object_or_404(Domain, pk=domain_id, tenant=palika)
    if d.is_primary:
        messages.error(request, "Primary डोमेन हटाउन मिल्दैन।")
    else:
        d.delete()
        messages.success(request, "डोमेन हटाइयो।")
    return redirect("saas_palika_detail", pk=pk)


@saas_staff_required
@require_POST
def palika_wards(request, pk):
    """SaaS Manager बाट पालिकाको कुल वडा संख्या मिलाउने (नभएका वडा थपिन्छन्, भएका छोइँदैनन्)."""
    from accounts.wards import MAX_WARDS, ensure_wards, np_num, ward_int

    palika = get_object_or_404(palikas(), pk=pk)
    n = ward_int(request.POST.get("total"))
    if n is None or not 1 <= n <= MAX_WARDS:
        messages.error(request, f"वडा संख्या १ देखि {np_num(MAX_WARDS)} सम्म हुनुपर्छ।")
    else:
        with schema_context(palika.schema_name):
            created = ensure_wards(n)
        if created:
            messages.success(request, f"{palika.full_name}: {np_num(len(created))} वटा वडा थपियो "
                                      f"({', '.join(w.name for w in created)})।")
        else:
            messages.info(request, f"{palika.full_name} मा वडा १–{np_num(n)} पहिले नै छन्।")
    return redirect("saas_palika_detail", pk=pk)
