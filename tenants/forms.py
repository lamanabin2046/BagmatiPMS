import re

from django import forms
from django.conf import settings

from .models import Palika

RESERVED = {"public", "www", "admin", "api", "static", "media", "mail", "saas"}


class _OfficerConflictOptional:
    """officer_conflict नपठाए पनि फारम चलोस् (पूर्वनिर्धारित: चेतावनी मात्र)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("officer_conflict", "min_user_contribution_pct", "retention_months"):
            if name in self.fields:
                self.fields[name].required = False

    def clean_officer_conflict(self):
        return self.cleaned_data.get("officer_conflict") or "warn"

    def clean_retention_months(self):
        v = self.cleaned_data.get("retention_months")
        if v is None:
            return getattr(self.instance, "retention_months", None) or 12
        if v > 120:
            raise forms.ValidationError("धरौटी फिर्ता अवधि १२० महिनाभन्दा बढी हुन सक्दैन।")
        return v

    def clean_min_user_contribution_pct(self):
        from decimal import Decimal

        v = self.cleaned_data.get("min_user_contribution_pct") or Decimal("0")
        if v < 0 or v > 100:
            raise forms.ValidationError("उपभोक्ता अंशदान न्यूनतम % ० देखि १०० बीच हुनुपर्छ।")
        return v


class PalikaCreateForm(_OfficerConflictOptional, forms.ModelForm):
    schema_name = forms.CharField(
        label="Subdomain / कोड",
        max_length=40,
        help_text="अंग्रेजी सानो अक्षर मात्र, जस्तै: bagmati → bagmati.<domain>",
    )
    number_of_wards = forms.IntegerField(label="वडा संख्या", min_value=0, max_value=40, initial=0, required=False)
    admin_name = forms.CharField(label="Admin को नाम", max_length=150, initial="Admin")
    admin_mobile = forms.CharField(label="Admin मोबाइल (login)", max_length=15)
    admin_password = forms.CharField(
        label="Admin password", required=False, widget=forms.PasswordInput(render_value=False),
        help_text="खाली छोडे आफैँ बन्छ र एकपटक देखाइन्छ।",
    )

    class Meta:
        model = Palika
        fields = [
            "name", "name_en", "palika_type", "uc_mode", "require_public_audit", "officer_conflict", "min_user_contribution_pct", "address", "district", "province",
            "office_name", "phone", "email", "website", "logo", "slogan", "show_govt_emblem", "letterhead_color",
            "letterhead_image", "cao_name", "bank_name",
            "plan", "paid_until", "contact_person", "contact_mobile",
        ]
        widgets = {"paid_until": forms.DateInput(attrs={"type": "date"})}

    def clean_schema_name(self):
        s = self.cleaned_data["schema_name"].strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9]{1,39}", s):
            raise forms.ValidationError("अंग्रेजी सानो अक्षर र अंक मात्र, अक्षरबाट सुरु (२–४० अक्षर)।")
        if s in RESERVED:
            raise forms.ValidationError("यो नाम प्रयोग गर्न मिल्दैन।")
        if Palika.objects.filter(schema_name=s).exists():
            raise forms.ValidationError("यो कोड पहिले नै प्रयोगमा छ।")
        return s

    def clean_admin_mobile(self):
        m = self.cleaned_data["admin_mobile"].strip()
        if not re.fullmatch(r"\d{7,15}", m):
            raise forms.ValidationError("अंक मात्र (७–१५ अंक)।")
        return m


class PalikaUpdateForm(_OfficerConflictOptional, forms.ModelForm):
    class Meta:
        model = Palika
        fields = PalikaCreateForm.Meta.fields + ["is_active"]
        widgets = PalikaCreateForm.Meta.widgets


class DomainForm(forms.Form):
    domain = forms.CharField(label="थप डोमेन", max_length=253, help_text="जस्तै: pms.bagmatimun.gov.np")

    def clean_domain(self):
        d = self.cleaned_data["domain"].strip().lower()
        if not re.fullmatch(r"[a-z0-9.-]+\.[a-z0-9-]+", d) and not d.endswith(".localhost"):
            raise forms.ValidationError("मान्य डोमेन लेख्नुहोस्।")
        from .models import Domain

        if Domain.objects.filter(domain=d).exists():
            raise forms.ValidationError("यो डोमेन पहिले नै जोडिएको छ।")
        return d


class OfficeSettingsForm(_OfficerConflictOptional, forms.ModelForm):
    """पालिकाको Admin आफैँले मिलाउने कार्यालय र पत्र शीर्ष सेटिङ (नाम, प्रकार र SaaS विवरण बाहेक)."""

    class Meta:
        model = Palika
        fields = [
            "office_name", "address", "district", "province", "phone", "email", "website",
            "slogan", "logo", "show_govt_emblem", "letterhead_color", "letterhead_image",
            "cao_name", "bank_name", "require_public_audit", "officer_conflict", "min_user_contribution_pct",
            "retention_months",
        ]

    def clean_logo(self):
        return _image_ok(self.cleaned_data.get("logo"))

    def clean_letterhead_image(self):
        return _image_ok(self.cleaned_data.get("letterhead_image"))


def _image_ok(f):
    if f and hasattr(f, "size") and f.size > 2 * 1024 * 1024:
        raise forms.ValidationError("image २ MB भन्दा सानो हुनुपर्छ।")
    return f
