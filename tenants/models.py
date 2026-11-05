"""
SaaS layer: one Palika = one tenant = one PostgreSQL schema.

Saving a new Palika creates its schema and all tables automatically
(auto_create_schema). provisioning.provision_palika() then adds the first
admin user and default lookup data.
"""
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin

# Logos are uploaded from the SaaS manager but shown on each palika's own site, so
# they use one fixed folder instead of the per-palika media storage.
# A callable (not an instance) so migrations store only this function's name, not the
# absolute folder path of whichever computer ran makemigrations.
def logo_storage():
    return FileSystemStorage(
        location=settings.MEDIA_ROOT / "palika_logos",
        base_url=settings.MEDIA_URL + "palika_logos/",
    )


class Palika(TenantMixin):
    PALIKA_TYPES = (
        ("गाउँपालिका", "गाउँपालिका"),
        ("नगरपालिका", "नगरपालिका"),
        ("उपमहानगरपालिका", "उपमहानगरपालिका"),
        ("महानगरपालिका", "महानगरपालिका"),
    )
    PLANS = (
        ("trial", "Trial"),
        ("basic", "Basic"),
        ("standard", "Standard"),
        ("premium", "Premium"),
    )

    # Identity (used on every letter, tippani and page header)
    name = models.CharField("पालिकाको नाम (नेपाली)", max_length=200, help_text="जस्तै: बागमती")
    name_en = models.CharField("Name (English)", max_length=200, blank=True)
    palika_type = models.CharField("प्रकार", max_length=30, choices=PALIKA_TYPES, default="गाउँपालिका")
    office_name = models.CharField(
        "कार्यालयको नाम", max_length=200, blank=True,
        help_text="खाली छोडे: गाउँ/नगर कार्यपालिकाको कार्यालय",
    )
    address = models.CharField("ठेगाना", max_length=200, blank=True, help_text="जस्तै: भट्टेडाँडा")
    district = models.CharField("जिल्ला", max_length=100, blank=True)
    province = models.CharField("प्रदेश", max_length=100, default="बागमती प्रदेश")
    phone = models.CharField("फोन", max_length=50, blank=True)
    email = models.EmailField("इमेल", blank=True)
    website = models.URLField("वेबसाइट", blank=True)
    logo = models.ImageField("लोगो", storage=logo_storage, upload_to="", blank=True, null=True)
    # पत्र शीर्ष (letter head) — टिप्पणी, बैंक पत्र, कार्यादेश लगायत सबै पत्रमा
    LETTERHEAD_COLORS = (
        ("#c4161c", "रातो"),
        ("#1e3a8a", "नीलो"),
        ("#14532d", "हरियो"),
        ("#111827", "कालो"),
    )
    slogan = models.CharField("नारा", max_length=250, blank=True, help_text="जस्तै: समृद्ध गाउँ, सुखी नागरिक")
    show_govt_emblem = models.BooleanField(
        "नेपाल सरकारको निशान छाप देखाउने", default=True,
        help_text="बायाँ निशान छाप, दायाँ पालिकाको लोगो। नदेखाए पालिकाको लोगो बायाँ आउँछ।",
    )
    letterhead_color = models.CharField("पत्र शीर्षको रङ", max_length=9, choices=LETTERHEAD_COLORS, default="#c4161c")
    letterhead_image = models.ImageField(
        "तयारी पत्र शीर्ष (image)", storage=logo_storage, upload_to="", blank=True, null=True,
        help_text="डिजाइन गरिसकेको पूरा पत्र शीर्ष (चौडा image) राखे, माथिका सट्टा यही छापिन्छ।",
    )
    cao_name = models.CharField("प्रमुख प्रशासकीय अधिकृतको नाम", max_length=200, blank=True)
    bank_name = models.CharField("मुख्य बैंक", max_length=200, blank=True)

    # उपभोक्ता समिति कार्यप्रवाह: who runs the agreement → payment process (default for all
    # projects; each project may override it)
    UC_MODES = (
        ("municipal", "पालिका केन्द्रित (पालिकाबाट सम्झौता/भुक्तानी, वडा सिफारिस अनिवार्य)"),
        ("ward", "वडा प्रत्यायोजित (वडाले नै सम्पूर्ण प्रक्रिया गर्ने)"),
    )
    uc_mode = models.CharField("उपभोक्ता समिति कार्यप्रवाह", max_length=20, choices=UC_MODES, default="municipal")
    require_public_audit = models.BooleanField(
        "सार्वजनिक परीक्षण अनिवार्य", default=False,
        help_text="अनिवार्य भए सार्वजनिक परीक्षण नभई अन्तिम भुक्तानी टिप्पणी र हस्तान्तरण छापिँदैन।",
    )
    OFFICER_CONFLICT = (
        ("warn", "चेतावनी मात्र दिने"),
        ("block", "रोक्ने (सुरक्षित र स्वीकृत हुँदैन)"),
    )
    officer_conflict = models.CharField(
        "एकै व्यक्ति धेरै सक्रिय समितिमा पदाधिकारी", max_length=10, choices=OFFICER_CONFLICT, default="warn",
    )
    min_user_contribution_pct = models.DecimalField(
        "उपभोक्ता अंशदान न्यूनतम (%)", max_digits=5, decimal_places=2, default=0,
        help_text="कुल लागत अनुमानको कम्तीमा यति % उपभोक्ता अंशदान (श्रमदान) हुनुपर्छ। ० = जाँच नगर्ने।",
    )
    retention_months = models.PositiveSmallIntegerField(
        "धरौटी फिर्ता अवधि (महिना)", default=12,
        help_text="अन्तिम बिल/भुक्तानी मितिदेखि यति महिना (त्रुटि सच्याउने अवधि) पछि धरौटी फिर्ता योग्य हुन्छ।",
    )

    # SaaS
    plan = models.CharField(max_length=20, choices=PLANS, default="trial")
    is_active = models.BooleanField("सक्रिय", default=True)
    paid_until = models.DateField("भुक्तानी म्याद", null=True, blank=True)
    contact_person = models.CharField(max_length=200, blank=True)
    contact_mobile = models.CharField(max_length=20, blank=True)
    provisioned = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True
    auto_drop_schema = False  # never drop a palika's data automatically

    class Meta:
        ordering = ["name"]
        verbose_name = "पालिका"
        verbose_name_plural = "पालिकाहरू"

    def __str__(self):
        return self.full_name or self.schema_name

    @property
    def full_name(self):
        if not self.name:
            return ""
        name = self.name.strip()
        # don't repeat the type if it was typed into the name ("मकवानपुरगढी गाउँपालिका")
        if any(name.endswith(t) for t, _ in self.PALIKA_TYPES):
            return name
        return f"{name} {self.palika_type}"

    @property
    def executive_office(self):
        if self.office_name:
            return self.office_name
        return "गाउँ कार्यपालिकाको कार्यालय" if self.palika_type == "गाउँपालिका" else "नगर कार्यपालिकाको कार्यालय"

    @property
    def assembly(self):
        return "गाउँसभा" if self.palika_type == "गाउँपालिका" else "नगरसभा"

    @property
    def contact_lines(self):
        """पत्र शीर्षको दायाँ भागका सम्पर्क विवरण."""
        lines = []
        if self.phone:
            lines.append(("फोन", self.phone))
        if self.email:
            lines.append(("इमेल", self.email))
        if self.website:
            lines.append(("वेबसाइट", self.website.replace("https://", "").replace("http://", "").rstrip("/")))
        return lines

    @property
    def location_line(self):
        return ", ".join(x for x in (self.address, self.district) if x)

    @property
    def primary_domain(self):
        d = self.domains.filter(is_primary=True).first()
        return d.domain if d else ""


class Domain(DomainMixin):
    class Meta:
        verbose_name = "डोमेन"
        verbose_name_plural = "डोमेनहरू"
