"""
Automatic setup of a new palika.

    palika = Palika(schema_name="bagmati", name="बागमती", ...)
    palika.save()                    # creates the schema + all tables (auto_create_schema)
    provision_palika(palika, ...)    # first admin user + default data

Everything here is idempotent: running it twice does not duplicate anything.
"""
import secrets

from django.db import transaction
from django_tenants.utils import schema_context

from .models import Domain, Palika

# The code filters projects by these ids (usercommittee=1, bidding=2, quotation=3),
# so they must be created first and in this exact order.
PROCUREMENT_TYPES = ["उपभोक्ता समिति", "सिलबन्दी बोलपत्र", "सिलबन्दी दरभाउ पत्र"]   # id १–३ (migration 0012 ले पनि बनाउँछ)
BUDGET_TYPES = ["स्थानीय तह", "संघीय", "प्रदेश"]
PROJECT_TYPES = ["वडा स्तरीय", "पालिका स्तरीय", "प्रदेश साझेदारी", "संघीय साझेदारी"]
NEPALI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def current_fiscal_year():
    """Nepali fiscal year (starts in Shrawan, ~mid July), e.g. '2083/84'."""
    try:
        import nepali_datetime

        today = nepali_datetime.date.today()
        start = today.year if today.month >= 4 else today.year - 1
    except Exception:  # library missing: approximate from the AD date
        from datetime import date

        d = date.today()
        start = d.year + 57 if (d.month, d.day) >= (7, 16) else d.year + 56
    return f"{start}/{str(start + 1)[-2:]}"


def palika_host(schema_name, base_domain):
    return f"{schema_name}.{base_domain}"


def create_palika(*, schema_name, name, base_domain, **fields):
    """Create the Palika row (which creates its schema) and its primary domain."""
    palika = Palika(schema_name=schema_name, name=name, **fields)
    palika.save()  # CREATE SCHEMA + migrate all TENANT_APPS into it
    Domain.objects.get_or_create(
        domain=palika_host(schema_name, base_domain),
        defaults={"tenant": palika, "is_primary": True},
    )
    return palika


def provision_palika(palika, *, admin_mobile, admin_name="Admin", admin_password=None, number_of_wards=0):
    """Add default data and the first admin user inside the palika's schema.

    Returns the admin password (generated if not given) so it can be shown once.
    """
    from accounts.models import Admin, CustomUser
    from projects.models import Budget_Type, FiscalYear, Procurement_Type, Project_Type

    password = admin_password or secrets.token_urlsafe(8)

    with schema_context(palika.schema_name), transaction.atomic():
        for n in PROCUREMENT_TYPES:
            Procurement_Type.objects.get_or_create(name=n)
        for n in BUDGET_TYPES:
            Budget_Type.objects.get_or_create(name=n)
        for n in PROJECT_TYPES:
            Project_Type.objects.get_or_create(type=n)
        FiscalYear.objects.get_or_create(name=current_fiscal_year())

        from accounts.wards import ensure_wards
        ensure_wards(number_of_wards or 0)

        user = CustomUser.objects.filter(mobile=admin_mobile).first()
        if user is None:
            user = CustomUser.objects.create_user(
                mobile=admin_mobile, password=password, user_type="1",
                is_staff=True, first_name=admin_name,
            )
        else:
            user.set_password(password)
            user.user_type = "1"
            user.is_active = True
            user.save()
        Admin.objects.get_or_create(admin=user, defaults={"name": admin_name, "mobile": admin_mobile})

    if not palika.provisioned:
        palika.provisioned = True
        palika.save(update_fields=["provisioned"])
    return password


def reset_admin_password(palika, admin_mobile):
    from accounts.models import CustomUser

    password = secrets.token_urlsafe(8)
    with schema_context(palika.schema_name):
        user = CustomUser.objects.get(mobile=admin_mobile)
        user.set_password(password)
        user.is_active = True
        user.save()
    return password


def ensure_public_tenant(base_domain):
    """The public schema row + domain that serves the SaaS manager."""
    public, _ = Palika.objects.get_or_create(
        schema_name="public", defaults={"name": "SaaS Manager", "provisioned": True}
    )
    Domain.objects.get_or_create(domain=base_domain, defaults={"tenant": public, "is_primary": True})
    if base_domain == "localhost":
        # local development: http://127.0.0.1:8000/ opens the SaaS manager too
        Domain.objects.get_or_create(domain="127.0.0.1", defaults={"tenant": public, "is_primary": False})
    return public
