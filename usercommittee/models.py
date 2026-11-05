from django.db import models
from django.conf import settings
from projects.models import Project
from accounts.models import WardSachib, PalikaEngineer
import json
from decimal import Decimal
from datetime import date
from django.core.exceptions import ValidationError
from projects.models import Project
# Create your models here.
from django.db import models


class UserCommittee(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="user_committee"
    )

    formation_date = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=250)

    # ================= CHAIRMAN =================
    chairman_name = models.CharField(max_length=250)
    chairman_citizenship = models.CharField(max_length=250, null=True, blank=True)
    chairman_mobile = models.CharField(max_length=20, null=True, blank=True)
    chairman_nid = models.CharField(max_length=50, null=True, blank=True)
    chairman_address = models.CharField(max_length=250, null=True, blank=True)

    # ================= SECRETARY =================
    secretary_name = models.CharField(max_length=250)
    secretary_citizenship = models.CharField(max_length=250, null=True, blank=True)
    secretary_mobile = models.CharField(max_length=20, null=True, blank=True)
    secretary_nid = models.CharField(max_length=50, null=True, blank=True)
    secretary_address = models.CharField(max_length=250, null=True, blank=True)

    # ================= TREASURER =================
    treasurer_name = models.CharField(max_length=250)
    treasurer_citizenship = models.CharField(max_length=250, null=True, blank=True)
    treasurer_mobile = models.CharField(max_length=20, null=True, blank=True)
    treasurer_nid = models.CharField(max_length=50, null=True, blank=True)
    treasurer_address = models.CharField(max_length=250, null=True, blank=True)

    # ================= MEMBERS (FLEXIBLE) =================
    """
    Expected JSON structure:
    [
        {
            "name": "राम थापा",
            "citizenship": "१२३४५",
            "mobile": "९८४१२३४५६७",
            "post": "member" | "vice_chairman",
            "nid": "...", "address": "..."
        }
    अध्यक्ष, सचिव र कोषाध्यक्ष माथिका आफ्नै field मा बस्छन्; बाँकी पद यहाँ।
    ]
    """
    members = models.JSONField(
        default=list,
        blank=True,
        help_text="List of committee members with name, citizenship, and mobile"
    )

    # ================= बैंक खाता (सम्झौतापछि खोलिने, भुक्तानी यसैमा जान्छ) =================
    bank_name = models.CharField("बैंक", max_length=200, blank=True, default="")
    bank_branch = models.CharField("शाखा", max_length=200, blank=True, default="")
    account_number = models.CharField("खाता नम्बर", max_length=60, blank=True, default="")
    account_name = models.CharField("खाताको नाम", max_length=250, blank=True, default="")
    account_opened_date = models.DateField("खाता खोलेको मिति", null=True, blank=True)

    @property
    def has_bank_account(self):
        return bool(self.bank_name and self.account_number)

    # ================= DATES =================
    start_date = models.DateField(null=True, blank=True)
    accomplish_date = models.DateField(null=True, blank=True)
    extended_date = models.DateField(null=True, blank=True)

    # ================= STATUS =================
    STATUS_CHOICES = (
        (0, "Draft"),
        (1, "Approved"),
        (2, "Completed"),
    )
    status = models.IntegerField(choices=STATUS_CHOICES, default=0)

    # ================= UTILITY METHODS =================
    @property
    def roster(self):
        """सबै पदाधिकारी र सदस्य, पदको क्रममा (print र फारमका लागि)।"""
        from .roster import roster_rows
        return roster_rows(self)

    def get_members_count(self):
        """समितिका कुल सदस्य संख्या (पदाधिकारी सहित)"""
        return len(self.roster)

    def has_members(self):
        return bool(self.members)

    # ================= म्याद / DEADLINE HELPERS =================
    @property
    def deadline(self):
        """Effective completion deadline: extended_date if the समिति's
        अवधि has been extended, else the originally agreed accomplish_date."""
        return self.extended_date or self.accomplish_date

    @property
    def days_left(self):
        """Days remaining until `deadline` (negative if already overdue).
        None when no deadline has been set at all."""
        if not self.deadline:
            return None
        return (self.deadline - date.today()).days

    @property
    def days_left_abs(self):
        return abs(self.days_left) if self.days_left is not None else None

    @property
    def is_overdue(self):
        """म्याद नाघेको तर काम अझै 'Completed' नभएको।"""
        return self.status != 2 and self.days_left is not None and self.days_left < 0

    @property
    def is_expiring_soon(self, within_days=30):
        """म्याद ३० दिनभित्र सकिन लागेको तर काम अझै 'Completed' नभएको।"""
        return (
            self.status != 2
            and self.days_left is not None
            and 0 <= self.days_left <= within_days
        )

    def __str__(self):
        return f"{self.name} ({self.project.name})"





    
class CostEstimate(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="cost_estimate"
    )

    budget = models.DecimalField(max_digits=12, decimal_places=2)
    contingency_amount = models.DecimalField(max_digits=12, decimal_places=2)
    user_contribution = models.DecimalField(max_digits=12, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)

    STATUS_CHOICES = (
        (0, "Draft"),
        (1, "Approved"),
    )
    status = models.IntegerField(choices=STATUS_CHOICES, default=0)
    # लागत अनुमानको स्क्यान / PDF (ऐच्छिक)
    document = models.FileField("लागत अनुमान कागजात", upload_to="cost_estimates/%Y/", null=True, blank=True)

    @property
    def office_contribution(self):
        return self.budget - self.contingency_amount

    def __str__(self):
        return self.project.name

  


class FinalPayment(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="final_payment"
    )

    application_date = models.DateField(null=True, blank=True)

    final_evaluation = models.DecimalField(max_digits=12, decimal_places=2)
    office_contribution = models.DecimalField(max_digits=12, decimal_places=2)
    user_contribution = models.DecimalField(max_digits=12, decimal_places=2)

    # Example: {"vat": 5000, "tds": 3000}
    tax_deduction = models.JSONField(default=dict, blank=True)

    total_tax = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    STATUS_CHOICES = (
        (0, "Pending"),
        (1, "Approved"),
        (2, "Paid"),
    )
    status = models.IntegerField(choices=STATUS_CHOICES, default=0)

    # Locks editing once the final-evaluation Tippani has been printed
    tippani_printed = models.BooleanField(default=False)
    # मूल्याङ्कन प्रतिवेदन / नापी किताबको स्क्यान वा PDF (ऐच्छिक)
    document = models.FileField("मूल्याङ्कन कागजात", upload_to="final_valuations/%Y/", null=True, blank=True)

    def calculate_total_tax(self):
        if not isinstance(self.tax_deduction, dict):
            raise ValidationError("Tax deduction must be a dictionary.")
        return sum(Decimal(str(v)) for v in self.tax_deduction.values())

    def save(self, *args, **kwargs):
        self.total_tax = self.calculate_total_tax()
        super().save(*args, **kwargs)

    @property
    def installments_paid(self):
        """यस अघि दिइएका किस्ता (पेश्की/रनिङ) को कुल रकम — अन्तिम भुक्तानीमा कट्टी हुन्छ."""
        from django.db.models import Sum

        return self.project.installments.aggregate(t=Sum("amount"))["t"] or Decimal("0")

    @property
    def net_payment(self):
        return self.office_contribution - self.total_tax - self.installments_paid

    def __str__(self):
        return self.project.name


class WardRecommendation(models.Model):
    """वडा कार्यालयको सिफारिस — the ward's recommendation letter for a
    उपभोक्ता समिति project agreement (सम्झौता). Issued by the WardSachib
    of the project's ward, and required before the agreement document
    (print_contract_paper.html) can be printed."""

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="ward_recommendation"
    )
    ward_sachib = models.ForeignKey(
        WardSachib,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendations"
    )

    letter_number = models.CharField(max_length=100, null=True, blank=True)
    chalani_number = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="चलानी नं. (dispatch/registration number)"
    )
    recommendation_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # पोर्टलबाट (वडा सचिवले यहीँ बनाएको) वा अपलोड (वडाले कागजमा पठाएको, स्क्यान गरी राखिएको)
    SOURCES = (("portal", "पोर्टल"), ("upload", "अपलोड"))
    source = models.CharField(max_length=10, choices=SOURCES, default="portal")
    document = models.FileField(upload_to="sifaris/", null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")

    def __str__(self):
        return f"सिफारिस – {self.project.name}"


class ProjectCompletionRecommendation(models.Model):
    """काम सम्पन्न सिफारिस — the ward's certification that a उपभोक्ता समिति
    project's work is complete, issued after the अन्तिम मूल्याङ्कन (final
    valuation) has been added. Required before हस्तान्तरण पत्र (handover
    letter) can be printed — the completion-stage counterpart of
    WardRecommendation, which gates the earlier agreement (सम्झौता)
    stage. Issued by the WardSachib of the project's ward."""

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="completion_recommendation"
    )
    ward_sachib = models.ForeignKey(
        WardSachib,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completion_recommendations"
    )

    letter_number = models.CharField(max_length=100, null=True, blank=True)
    chalani_number = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="चलानी नं. (dispatch/registration number)"
    )
    recommendation_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # पोर्टलबाट (वडा सचिवले यहीँ बनाएको) वा अपलोड (वडाले कागजमा पठाएको, स्क्यान गरी राखिएको)
    SOURCES = (("portal", "पोर्टल"), ("upload", "अपलोड"))
    source = models.CharField(max_length=10, choices=SOURCES, default="portal")
    document = models.FileField(upload_to="sifaris/", null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")

    def __str__(self):
        return f"काम सम्पन्न सिफारिस – {self.project.name}"


class SiteInspectionNote(models.Model):
    """प्राविधिक टिप्पणी / साइट निरीक्षण — a Palika Engineer's own dated
    site-visit note against a project, independent of the Ward
    Engineer's photo timeline. A project can accumulate several of
    these over its life (repeat site visits), so this is a plain FK,
    not a OneToOne like the other workflow-stage models above."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="inspection_notes"
    )
    palika_engineer = models.ForeignKey(
        PalikaEngineer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspection_notes"
    )

    inspection_date = models.DateField(null=True, blank=True)
    remarks = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"निरीक्षण टिप्पणी – {self.project.name}"


class ActivityLog(models.Model):
    """परिवर्तन लग (audit trail) — कसले, कहिले, उपभोक्ता समिति/लागत
    अनुमान/अन्तिम भुक्तानीमा के गर्यो भन्ने अभिलेख। हरेक सम्बन्धित view
    ले सम्बन्धित .save()/.objects.create() पछि स्पष्ट रूपमा
    log_activity() बोलाएर यो रेकर्ड बनाउँछ (सिग्नल प्रयोग गरिएको छैन,
    ताकि हरेक इन्ट्रीमा सधैं request.user पक्का उपलब्ध होस्)।

    object_id/object_repr/project_name सबै त्यही बेलाको स्न्यापसट हुन् —
    पछि सम्बन्धित रेकर्ड मेटिए/बदलिए पनि यो लग यथावत रहन्छ।"""

    ACTION_CHOICES = (
        ("create", "थपियो"),
        ("update", "सम्पादन गरियो"),
        ("delete", "मेटियो"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100)  # जस्तै: "उपभोक्ता समिति", "लागत अनुमान"
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    project_name = models.CharField(max_length=255, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} – {self.model_name} #{self.object_id}"

class DocumentPrint(models.Model):
    """Records each time an official document is printed for a project, so the
    कार्यप्रवाह (workflow) tracker can show which documents are done."""

    CONTRACT = "contract"
    TIPPANI = "tippani"
    BANK_LETTER = "bank_letter"
    WORK_ORDER = "work_order"
    FINAL_TIPPANI = "final_tippani"
    HANDOVER = "handover"
    DOC_CHOICES = (
        (CONTRACT, "सम्झौता पत्र"),
        (TIPPANI, "टिप्पणी"),
        (BANK_LETTER, "बैंक पत्र"),
        (WORK_ORDER, "कार्यादेश"),
        (FINAL_TIPPANI, "अन्तिम टिप्पणी"),
        (HANDOVER, "हस्तान्तरण पत्र"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="document_prints")
    doc_type = models.CharField(max_length=30, choices=DOC_CHOICES)
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    printed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["printed_at"]

    def __str__(self):
        return f"{self.project} – {self.get_doc_type_display()}"


class UCApproval(models.Model):
    """रुजु/स्वीकृत of the agreement with the उपभोक्ता समिति (one step, before सम्झौता)."""
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="uc_approval")
    mode = models.CharField(max_length=20)  # municipal | ward (at the time of approval)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    related_name="+")
    approver_name = models.CharField(max_length=250, blank=True)
    approver_post = models.CharField(max_length=250, blank=True)
    remarks = models.TextField(blank=True)
    approved_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"स्वीकृत – {self.project}"


# ================= व्यक्ति अभिलेख (उपभोक्ता समितिका सदस्य) =================
def _person_doc_path(instance, filename):
    import os
    import uuid

    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"persons/{instance.pk or 'new'}/{uuid.uuid4().hex[:12]}{ext}"


class Person(models.Model):
    """समितिमा बसेका व्यक्तिको स्थायी अभिलेख। फेरि अर्को समितिमा आउँदा NID वा
    नागरिकता नम्बरबाट भेटिन्छ, कागजात फेरि माग्नु पर्दैन।"""

    DOC_KINDS = [
        ("photo", "फोटो"),
        ("citizenship_front", "नागरिकता (अगाडि)"),
        ("citizenship_back", "नागरिकता (पछाडि)"),
        ("nid_card", "राष्ट्रिय परिचयपत्र"),
    ]

    nid = models.CharField(max_length=20, blank=True, default="", db_index=True)  # 435-6756-65
    citizenship_no = models.CharField(max_length=50, blank=True, default="", db_index=True)
    name = models.CharField(max_length=250)
    name_en = models.CharField(max_length=250, blank=True, default="")
    gender = models.CharField(max_length=20, blank=True, default="")
    address = models.CharField(max_length=250, blank=True, default="")
    mobile = models.CharField(max_length=20, blank=True, default="")

    photo = models.FileField(upload_to=_person_doc_path, blank=True)
    citizenship_front = models.FileField(upload_to=_person_doc_path, blank=True)
    citizenship_back = models.FileField(upload_to=_person_doc_path, blank=True)
    nid_card = models.FileField(upload_to=_person_doc_path, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.nid or self.citizenship_no or '—'})"

    # ---- कागजात ----
    def doc(self, kind):
        f = getattr(self, kind, None)
        return f if f and f.name else None

    @property
    def has_identity(self):
        """परिचय प्रमाण: नागरिकता दुवै पाटा, वा राष्ट्रिय परिचयपत्र।"""
        return bool(self.doc("nid_card") or (self.doc("citizenship_front") and self.doc("citizenship_back")))

    @property
    def missing_docs(self):
        """स्वीकृतका लागि नपुगेका कागजात (खाली = पुग्यो)।"""
        missing = []
        if not self.doc("photo"):
            missing.append("फोटो")
        if not self.has_identity:
            missing.append("नागरिकता (दुवै पाटा) वा राष्ट्रिय परिचयपत्र")
        return missing

    @property
    def docs_complete(self):
        return not self.missing_docs


class CommitteeMember(models.Model):
    """कुन समितिमा कुन व्यक्ति कुन पदमा।"""
    committee = models.ForeignKey(UserCommittee, on_delete=models.CASCADE, related_name="member_links")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="memberships")
    post = models.CharField(max_length=20, default="member")
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]
        unique_together = ("committee", "person")

    def __str__(self):
        return f"{self.committee_id}:{self.post}:{self.person_id}"


# ================= कर शीर्षक (पालिकाअनुसार फरक) =================
class TaxHead(models.Model):
    """अन्तिम भुक्तानीमा कट्टी हुने करका शीर्षक। FinalPayment.tax_deduction मा {code: रकम} बस्छ।"""
    name = models.CharField("कर शीर्षक", max_length=150)
    code = models.CharField(max_length=40, unique=True)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField("सक्रिय", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name



# ================= किस्ता भुक्तानी (पेश्की / रनिङ बिल) =================
class Installment(models.Model):
    KINDS = (("advance", "पेश्की"), ("running", "रनिङ बिल"))

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="installments")
    number = models.PositiveIntegerField("किस्ता नं.")
    kind = models.CharField("प्रकार", max_length=10, choices=KINDS, default="running")
    date = models.DateField("मिति", null=True, blank=True)
    work_value = models.DecimalField("सम्पन्न कामको मूल्याङ्कन", max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField("भुक्तानी रकम", max_digits=12, decimal_places=2)
    tax_deduction = models.JSONField(default=dict, blank=True)
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remarks = models.TextField("कैफियत", blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        unique_together = ("project", "number")

    def save(self, *args, **kwargs):
        self.total_tax = sum(Decimal(str(v)) for v in (self.tax_deduction or {}).values())
        super().save(*args, **kwargs)

    @property
    def net_amount(self):
        return self.amount - self.total_tax

    @property
    def label(self):
        return f"{self.get_kind_display()} — {self.number} औं किस्ता"

    def __str__(self):
        return f"{self.project_id} #{self.number}"


# ================= सार्वजनिक परीक्षण / सुनुवाइ र अनुगमन =================
class PublicAudit(models.Model):
    FINDINGS = (("ok", "सन्तोषजनक"), ("improve", "सुधार गर्नुपर्ने"), ("bad", "असन्तोषजनक"))

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="public_audit")
    # सार्वजनिक परीक्षण / सुनुवाइ
    date = models.DateField("मिति", null=True, blank=True)
    venue = models.CharField("स्थान", max_length=250, blank=True, default="")
    chaired_by = models.CharField("अध्यक्षता", max_length=250, blank=True, default="")
    participants_total = models.PositiveIntegerField("कुल सहभागी", default=0)
    participants_women = models.PositiveIntegerField("महिला सहभागी", default=0)
    income_presented = models.DecimalField("आम्दानी (प्रस्तुत)", max_digits=12, decimal_places=2, null=True, blank=True)
    expense_presented = models.DecimalField("खर्च (प्रस्तुत)", max_digits=12, decimal_places=2, null=True, blank=True)
    decision = models.TextField("निर्णय", blank=True, default="")
    issues = models.TextField("उठेका सवाल / गुनासो", blank=True, default="")
    # अनुगमन समिति
    monitoring_date = models.DateField("अनुगमन मिति", null=True, blank=True)
    monitoring_members = models.TextField("अनुगमन समितिका सदस्य", blank=True, default="")
    monitoring_finding = models.CharField("अनुगमनको निष्कर्ष", max_length=10, choices=FINDINGS, blank=True, default="")
    monitoring_remarks = models.TextField("अनुगमन समितिको सुझाव", blank=True, default="")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def women_pct(self):
        return round(self.participants_women * 100 / self.participants_total) if self.participants_total else 0

    def __str__(self):
        return f"सार्वजनिक परीक्षण: {self.project_id}"


def _audit_file_path(instance, filename):
    import os
    import uuid

    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"public_audit/{instance.audit.project_id}/{uuid.uuid4().hex[:12]}{ext}"


class PublicAuditFile(models.Model):
    KINDS = (
        ("minutes", "मुचुल्का / निर्णय"),
        ("attendance", "उपस्थिति"),
        ("photo", "फोटो"),
        ("monitoring", "अनुगमन प्रतिवेदन"),
        ("other", "अन्य"),
    )
    audit = models.ForeignKey(PublicAudit, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=12, choices=KINDS, default="other")
    file = models.FileField(upload_to=_audit_file_path)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "id"]

    @property
    def is_image(self):
        return self.file.name.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp", "gif")
