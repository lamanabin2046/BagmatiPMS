from django.db import models
from projects.models import Project
from django.core.exceptions import ValidationError

# Create your models here.
class Suchikrit(models.Model):
    """फर्म / निर्माण व्यवसायी दर्ता (पालिकाको एउटै सूची) — दरभाउपत्रका सूचीकृत फर्म पनि यही।
    कालोसूची: blacklisted र (म्याद नतोकिएको वा म्याद बाँकी) भए खरिदमा सहभागी हुन नपाउने।"""
    KINDS = (("contractor", "निर्माण व्यवसायी"), ("supplier", "आपूर्तिकर्ता"), ("consultant", "परामर्शदाता"),
             ("organization", "संस्था / समिति"), ("revenue", "राजस्व ठेकेदार"))
    CLASSES = (("", "—"), ("ka", "क वर्ग"), ("kha", "ख वर्ग"), ("ga", "ग वर्ग"), ("gha", "घ वर्ग"))
    firm_name = models.CharField(max_length=250)
    firm_owner = models.CharField(max_length=250, blank=True, default="")
    firm_address = models.CharField(max_length=250, blank=True, default="")
    firm_pan = models.CharField(max_length=250, blank=True, default="")
    firm_contact = models.CharField(max_length=250, blank=True, default="")
    suchikrit_date =  models.DateField(null=True, blank=True)
    kind = models.CharField("प्रकार", max_length=20, choices=KINDS, default="contractor")
    vat_registered = models.BooleanField("भ्याट दर्ता", default=False)
    reg_no = models.CharField("दर्ता नं.", max_length=100, blank=True, default="")
    contractor_class = models.CharField("निर्माण व्यवसायी वर्ग", max_length=10, choices=CLASSES, blank=True, default="")
    email = models.CharField("इमेल", max_length=150, blank=True, default="")
    enlisted = models.BooleanField("दरभाउपत्रका लागि सूचीकृत", default=True)
    is_active = models.BooleanField("सक्रिय", default=True)
    blacklisted = models.BooleanField("कालोसूचीमा", default=False)
    blacklist_until = models.DateField("कालोसूची म्याद", null=True, blank=True)
    blacklist_ref = models.CharField("कालोसूची निर्णय / PPMO सूचना", max_length=200, blank=True, default="")
    blacklist_reason = models.TextField("कालोसूचीको कारण", blank=True, default="")
    notes = models.TextField("कैफियत", blank=True, default="")
    # IRD (PAN) बाट ल्याइएको विवरण
    ird_name = models.CharField("IRD मा दर्ता नाम", max_length=250, blank=True, default="")
    ird_status = models.CharField("IRD खाता स्थिति", max_length=100, blank=True, default="")
    ird_checked_at = models.DateTimeField("IRD जाँच मिति", null=True, blank=True)
    ird_data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.firm_name

    @property
    def is_blacklisted(self):
        from datetime import date

        return bool(self.blacklisted and (self.blacklist_until is None or self.blacklist_until >= date.today()))
    
    
class Quation(models.Model):
    suchikrit = models.ManyToManyField(Suchikrit, related_name='quations')
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    cost_estimate = models.DecimalField(max_digits=12, decimal_places=2)
    contingency = models.FloatField(null=True)
    is_selected = models.BooleanField(default=False)
    is_invited = models.BooleanField(default=False)
    bidded_prices = models.JSONField(null=True, blank=True)  # Field to store all bidded prices
    agreement_date = models.DateField(null=True)
    expire_date = models.DateField(null=True)
    # कार्यप्रवाह: आह्वान र प्राप्ति मितिहरू
    invite_date = models.DateField("आह्वान मिति", null=True, blank=True)
    submission_deadline = models.DateField("दरभाउपत्र पेश गर्ने अन्तिम मिति", null=True, blank=True)
    opening_date = models.DateField("दरभाउपत्र खोलेको मिति", null=True, blank=True)

    def __str__(self):
        return f"{self.project.name} - {', '.join([firm.firm_name for firm in self.suchikrit.all()])}"

    def clean(self):
        # Custom validation to enforce uniqueness between suchikrit and project
        if self.suchikrit.count() > 0:
            for firm in self.suchikrit.all():
                if Quation.objects.filter(suchikrit=firm, project=self.project).exists():
                    raise ValidationError(f"Firm {firm.firm_name} is already associated with this project.")
                
            
                
class QuationFinal(models.Model):
    quation = models.ForeignKey(Quation, on_delete=models.CASCADE)
    application_date =models.DateField(null=True)
    totalValuation = models.FloatField(null=True)
    retension = models.FloatField(null=True)
    taxdeduction = models.FloatField(null=True)
    finalpayment = models.FloatField(null=True)
    advance_deducted = models.FloatField("अग्रिम कट्टी", default=0)
    
    def __str__(self):
        return f"{self.quation.project.name} - {self.finalpayment}"



# ================= कार्यप्रवाह (workflow) =================
from django.conf import settings as _settings


class QuationApproval(models.Model):
    """न्यूनतम दरभाउपत्र स्वीकृत (प्रमुख प्रशासकीय अधिकृत वा अनुमति पाएका)."""
    quation = models.OneToOneField(Quation, on_delete=models.CASCADE, related_name="approval")
    approved_by = models.ForeignKey(_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    approver_name = models.CharField(max_length=200, blank=True)
    approver_post = models.CharField(max_length=200, blank=True)
    firm_name = models.CharField("स्वीकृत फर्म", max_length=250, blank=True)
    amount = models.DecimalField("स्वीकृत रकम", max_digits=14, decimal_places=2, null=True, blank=True)
    remarks = models.TextField(blank=True)
    approved_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"स्वीकृत – {self.quation}"


class QuationPrint(models.Model):
    """दरभाउपत्रका कागजात छापिएको अभिलेख — कार्यप्रवाहमा चरण पूरा देखाउन."""
    DOC_CHOICES = (
        ("invite_tippani", "आह्वान टिप्पणी"),
        ("invite_letter", "आह्वान पत्र"),
        ("approval_tippani", "स्वीकृति टिप्पणी"),
        ("agreement", "सम्झौता"),
        ("work_order", "कार्यादेश"),
        ("final_tippani", "अन्तिम भुक्तानी टिप्पणी"),
    )
    quation = models.ForeignKey(Quation, on_delete=models.CASCADE, related_name="prints")
    doc_type = models.CharField(max_length=30, choices=DOC_CHOICES)
    printed_by = models.ForeignKey(_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    printed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["printed_at"]


class QuationAdvance(models.Model):
    """अग्रिम भुक्तानी (पेश्की) र त्यसको बैंक जमानत — बोलपत्रकै जस्तो; अन्तिम बिलमा कट्टी हुन्छ."""
    quation = models.ForeignKey(Quation, on_delete=models.CASCADE, related_name="advances")
    approved_amount = models.DecimalField("अग्रिम रकम", max_digits=14, decimal_places=2)
    approval_date = models.DateField("स्वीकृत मिति")
    remarks = models.TextField(blank=True)
    # अग्रिम भुक्तानी जमानत (बैंक ग्यारेन्टी)
    bank_name = models.CharField("बैंक", max_length=250)
    guarantee_number = models.CharField("जमानत नम्बर", max_length=250)
    guaranteed_amount = models.DecimalField("जमानत रकम", max_digits=14, decimal_places=2)
    issue_date = models.DateField("जारी मिति")
    expiry_date = models.DateField("म्याद")
    document = models.FileField(upload_to="advance_guarantees/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["approval_date", "id"]

    @property
    def days_left(self):
        from datetime import date

        return (self.expiry_date - date.today()).days

    def __str__(self):
        return f"अग्रिम – {self.quation.project.name} ({self.approved_amount})"
