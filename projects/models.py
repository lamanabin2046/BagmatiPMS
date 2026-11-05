from decimal import Decimal

from django.db import models

from accounts.models import Ward


class FiscalYear(models.Model):
    name = models.CharField(max_length=100)
    # आ.व. बन्द (projects/yearend.py): बन्दपछि यस आ.व. का योजनामा भुक्तानी / बजेट परिवर्तन हुँदैन
    closed_at = models.DateTimeField("बन्द गरिएको", null=True, blank=True)
    closed_by = models.ForeignKey("accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    close_ref = models.CharField("बन्द गर्ने निर्णय", max_length=200, blank=True)
    # चालु आ.व. (projects/fiscal.py) — कार्यप्रवाह, खरिद योजना, बजेट र नयाँ योजना यही आ.व. का मात्र; एउटा मात्र True
    is_current = models.BooleanField("चालु आ.व.", default=False)

    def __str__(self):
        return self.name


 
class Project_Type(models.Model):
    type = models.CharField(max_length=100)
    def __str__(self):
        return self.type

class Budget_Type(models.Model):
    name = models.CharField(max_length=250)
    def __str__(self):
        return self.name     
    
    
class Procurement_Type(models.Model):
    name = models.CharField(max_length=250)
    # स्थिर कोड: uc (उपभोक्ता समिति), bid (बोलपत्र), quot (दरभाउपत्र), sanstha, amanat, direct — projects/procurement.py
    code = models.CharField(max_length=20, blank=True, default="", db_index=True)
    def __str__(self):
        return self.name
    
    

    
class Project(models.Model):
    STATUS_CHOICES = [
        (0, 'Open for Bids'),
        (1, 'In Progress'),
        (2, 'Completed'),
    ]
    fiscalyear = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, null=True)
    name = models.CharField(max_length=250)
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, null=True)
    procurement_type = models.ForeignKey(Procurement_Type, on_delete=models.CASCADE, null=True)
    budget_type = models.ForeignKey(Budget_Type, on_delete=models.CASCADE, null=True)
    project_type = models.ForeignKey(Project_Type,on_delete=models.CASCADE,null=True)
    address = models.TextField()
    budget = models.FloatField()
    # '' = use the palika's default (Palika.uc_mode)
    EXECUTION_MODES = (
        ("", "पालिकाको नियम अनुसार"),
        ("municipal", "पालिका केन्द्रित"),
        ("ward", "वडा प्रत्यायोजित"),
    )
    execution_mode = models.CharField("कार्यान्वयन तह", max_length=20, choices=EXECUTION_MODES, blank=True, default="")
    status = models.IntegerField(default=0)
    # योजना स्थल (पहिलो GPS फोटोबाट वा हातैले)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # क्रमागत योजना: अघिल्लो आ.व. बाट सारिएको भए त्यो आ.व. र त्यतिबेलासम्मको खर्च
    carried_from = models.ForeignKey("FiscalYear", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    spent_before = models.DecimalField("अघिल्ला आ.व. मा खर्च", max_digits=16, decimal_places=2, default=0)
    # कामको प्रकार (सडक, भवन …) — भौतिक उपलब्धि (ProjectOutput) भर्दा छानिन्छ
    work_category = models.ForeignKey("WorkCategory", on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="projects", verbose_name="कामको प्रकार")
    # क्षेत्र / उपक्षेत्र (स्थानीय तहको बजेट वर्गीकरण — पालिकाले सेटिङबाट मिलाउन मिल्ने)
    sector = models.ForeignKey("Sector", on_delete=models.SET_NULL, null=True, blank=True, related_name="projects",
                               verbose_name="क्षेत्र")
    subsector = models.ForeignKey("SubSector", on_delete=models.SET_NULL, null=True, blank=True, related_name="projects",
                                  verbose_name="उपक्षेत्र")
    # बजेट उपशीर्षक / कार्यक्रम (बजेट नियन्त्रण) — विनियोजित रकम यही शीर्षकको सीमाभित्र
    budget_head = models.ForeignKey("BudgetHead", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="projects", verbose_name="बजेट शीर्षक")


    def __str__(self):
        return f"{self.name} ({self.fiscalyear.name})"
    
    
    


from django.db import models
from django.conf import settings
from .models import Project

# ================= क्षेत्र / उपक्षेत्र =================
class Sector(models.Model):
    """क्षेत्र: आर्थिक विकास, सामाजिक विकास, पूर्वाधार विकास …"""
    name = models.CharField("क्षेत्र", max_length=150)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField("सक्रिय", default=True)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name


class SubSector(models.Model):
    """उपक्षेत्र: शिक्षा, स्वास्थ्य, सडक तथा पुल … (एउटा क्षेत्रभित्र)."""
    sector = models.ForeignKey(Sector, on_delete=models.CASCADE, related_name="subsectors")
    name = models.CharField("उपक्षेत्र", max_length=150)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField("सक्रिय", default=True)

    class Meta:
        ordering = ["sector__sort", "sector_id", "sort", "id"]

    def __str__(self):
        return self.name


# ================= भौतिक उपलब्धि (कति कि.मि. बाटो, कति भवन …) =================
class WorkCategory(models.Model):
    """कामको प्रकार: सडक/बाटो, भवन, खानेपानी … (पालिकाले थप्न/बदल्न मिल्ने)."""
    name = models.CharField("कामको प्रकार", max_length=150)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField("सक्रिय", default=True)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name


class OutputIndicator(models.Model):
    """उपलब्धि सूचक: जस्तै "नयाँ ट्रयाक (कच्ची बाटो)" — कि.मि.; "नयाँ भवन" — वटा."""
    category = models.ForeignKey(WorkCategory, on_delete=models.CASCADE, related_name="indicators")
    name = models.CharField("उपलब्धि", max_length=200)
    unit = models.CharField("एकाइ", max_length=40)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField("सक्रिय", default=True)

    class Meta:
        ordering = ["category__sort", "category_id", "sort", "id"]

    def __str__(self):
        return f"{self.name} ({self.unit})"


class ProjectOutput(models.Model):
    """एउटा योजनाको एउटा सूचकको परिमाण — प्रतिवेदनमा जोडिन्छ।"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="outputs")
    indicator = models.ForeignKey(OutputIndicator, on_delete=models.PROTECT, related_name="values")
    quantity = models.DecimalField("परिमाण", max_digits=14, decimal_places=3)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("project", "indicator")
        ordering = ["indicator__category__sort", "indicator__sort", "indicator_id"]

    def __str__(self):
        return f"{self.project_id}: {self.indicator} = {self.quantity}"


class ProjectTimeline(models.Model):
    # काम सुरु हुनु अघि / भइरहेको बेला / सम्पन्न भएपछि — the three checkpoints
    # a Ward Engineer must photograph for every project. Left nullable so
    # older, free-form timeline entries (uploaded before this field existed)
    # keep working unchanged.
    STAGE_BEFORE = 1
    STAGE_DURING = 2
    STAGE_AFTER = 3
    STAGE_CHOICES = (
        (STAGE_BEFORE, "काम सुरु हुनु अघि"),
        (STAGE_DURING, "काम भइरहेको बेला"),
        (STAGE_AFTER, "काम सम्पन्न भएपछि"),
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="timelines"
    )

    stage = models.IntegerField(choices=STAGE_CHOICES, null=True, blank=True)

    image = models.ImageField(
        upload_to="project_timelines/"
    )
    # साइटबाट (मोबाइल) — GPS, खिचेको समय, भौतिक प्रगति (projects/field.py)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy = models.PositiveIntegerField("GPS शुद्धता (मिटर)", null=True, blank=True)
    distance_m = models.PositiveIntegerField("योजना स्थलबाट दूरी (मिटर)", null=True, blank=True)
    progress_pct = models.PositiveSmallIntegerField("भौतिक प्रगति %", null=True, blank=True)
    from_field = models.BooleanField("साइटबाट (मोबाइल)", default=False)
    is_public = models.BooleanField("नागरिक पेजमा देखाउने", default=True)

    description = models.TextField()

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]   # 🔥 auto timeline

    def __str__(self):
        return f"{self.project.name} - {self.created_at}"


def project_uc_mode(project):
    """'municipal' or 'ward' for a उपभोक्ता समिति project (project override, else the palika default)."""
    if getattr(project, "execution_mode", ""):
        return project.execution_mode
    from django.db import connection

    return getattr(getattr(connection, "tenant", None), "uc_mode", None) or "municipal"



# ================= धरौटी फिर्ता (उपभोक्ता समिति / बोलपत्र / दरभाउपत्र) =================
class RetentionRelease(models.Model):
    """एउटा योजनाको धरौटी फिर्ता: इन्जिनियर/वडाको सिफारिस (अपलोड) → टिप्पणी → फिर्ता दर्ता."""
    REC_BY = (("engineer", "इन्जिनियर (प्राविधिक)"), ("ward", "वडा कार्यालय"))
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="retention_release")
    held_amount = models.DecimalField("रोक्का धरौटी", max_digits=14, decimal_places=2, default=0)
    # सिफारिस
    rec_by = models.CharField("सिफारिस गर्ने", max_length=20, choices=REC_BY, default="engineer")
    rec_number = models.CharField("पत्र संख्या / च.नं.", max_length=100, blank=True)
    rec_date = models.DateField("सिफारिस मिति")
    rec_document = models.FileField("सिफारिस पत्र", upload_to="retention/")
    rec_remarks = models.TextField("कैफियत", blank=True)
    rec_uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="+")
    rec_uploaded_at = models.DateTimeField(auto_now_add=True)
    # टिप्पणी
    tippani_printed_at = models.DateTimeField(null=True, blank=True)
    # फिर्ता
    released_on = models.DateField("फिर्ता मिति", null=True, blank=True)
    released_amount = models.DecimalField("फिर्ता रकम", max_digits=14, decimal_places=2, null=True, blank=True)
    voucher_number = models.CharField("भौचर / चेक नं.", max_length=100, blank=True)
    approved_document = models.FileField("सदर भएको टिप्पणी (स्क्यान)", upload_to="retention/", null=True, blank=True)
    early_reason = models.TextField("म्यादअघि फिर्ताको कारण", blank=True)
    released_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")

    def __str__(self):
        return f"धरौटी फिर्ता – {self.project.name}"



# ================= बजेट नियन्त्रण =================
class BudgetHead(models.Model):
    """बजेट उपशीर्षक / कार्यक्रम — आ.व.अनुसार स्वीकृत (विनियोजित) रकम.
    यस शीर्षकमा राखिएका योजनाको विनियोजित रकमको जोड यो रकमभन्दा बढी हुन पाउँदैन।"""
    fiscalyear = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="budget_heads",
                                   verbose_name="आर्थिक वर्ष")
    code = models.CharField("बजेट उपशीर्षक नं.", max_length=50, blank=True)
    name = models.CharField("शीर्षक / कार्यक्रम", max_length=250)
    budget_type = models.ForeignKey(Budget_Type, on_delete=models.SET_NULL, null=True, blank=True,
                                    verbose_name="स्रोत / बजेट प्रकार")
    allocated = models.DecimalField("स्वीकृत रकम", max_digits=16, decimal_places=2, default=0)
    is_active = models.BooleanField("सक्रिय", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fiscalyear_id", "code", "id"]

    def __str__(self):
        return f"{self.code} {self.name}".strip()


class BudgetAmendment(models.Model):
    """विनियोजित रकमको संशोधन: थप (थप बजेट), कटौती / समर्पण, वा योजनाबीच रकमान्तर.
    दर्ता हुनेबित्तिकै योजनाको विनियोजित रकम (Project.budget) बदलिन्छ; पहिले/पछिको रकम यहीँ रहन्छ।"""
    KINDS = (("increase", "थप"), ("decrease", "कटौती / समर्पण"), ("transfer", "रकमान्तर"))
    kind = models.CharField("प्रकार", max_length=20, choices=KINDS)
    from_project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="budget_out", verbose_name="घटाउने योजना")
    to_project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name="budget_in", verbose_name="थप्ने योजना")
    amount = models.DecimalField("रकम", max_digits=16, decimal_places=2)
    from_before = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    from_after = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    to_before = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    to_after = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    decision_by = models.CharField("निर्णय गर्ने", max_length=150, blank=True)
    decision_no = models.CharField("निर्णय नं.", max_length=100, blank=True)
    decision_date = models.DateField("निर्णय मिति")
    reason = models.TextField("कारण")
    document = models.FileField("निर्णयको प्रतिलिपि", upload_to="budget/", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-decision_date", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} रु. {self.amount}"



# ================= वार्षिक खरिद योजना =================
class ProcurementLimits(models.Model):
    """खरिद विधिका रकम सीमा (पालिकाले सेटिङबाट मिलाउन मिल्ने — कानुन संशोधन हुँदा)."""
    direct_limit = models.DecimalField("सोझै खरिद सीमा (निर्माण / मालसामान / अन्य सेवा)", max_digits=16, decimal_places=2,
                                       default=1000000)
    consult_direct_limit = models.DecimalField("सोझै खरिद सीमा (परामर्श सेवा)", max_digits=16, decimal_places=2, default=500000)
    quot_limit = models.DecimalField("सिलबन्दी दरभाउपत्र सीमा", max_digits=16, decimal_places=2, default=2000000)
    uc_limit = models.DecimalField("उपभोक्ता समिति सीमा", max_digits=16, decimal_places=2, default=1000000)
    sanstha_notice_limit = models.DecimalField("संस्था/समिति — यसभन्दा बढीमा खुला आशयपत्र (EOI)", max_digits=16,
                                               decimal_places=2, default=1000000)
    app_required_above = models.DecimalField("वार्षिक खरिद योजना अनिवार्य (वार्षिक खरिद यसभन्दा बढी)", max_digits=16,
                                             decimal_places=2, default=1000000)
    mpp_required_above = models.DecimalField("खरिद गुरुयोजना अनिवार्य (वार्षिक खरिद यसभन्दा बढी)", max_digits=16,
                                             decimal_places=2, default=100000000)
    note = models.TextField("कानुनी आधार / टिप्पणी", blank=True)
    # कन्टिन्जेन्सी कट्टी दर (लागत अनुमानको %) — पालिकाअनुसार फरक हुन सक्ने
    contingency_uc = models.DecimalField("कन्टिन्जेन्सी — उपभोक्ता समिति (%)", max_digits=5, decimal_places=2, default=Decimal("3"))
    contingency_bid = models.DecimalField("कन्टिन्जेन्सी — बोलपत्र ठेक्का (%)", max_digits=5, decimal_places=2, default=Decimal("3"))
    contingency_quot = models.DecimalField("कन्टिन्जेन्सी — दरभाउपत्र (%)", max_digits=5, decimal_places=2, default=Decimal("3"))
    require_approved_plan = models.BooleanField("खरिद योजना स्वीकृत नभई खरिद प्रक्रिया सुरु गर्न नदिने", default=True)
    # सम्झौता व्यवस्थापन (बोलपत्र)
    ld_rate_per_day = models.DecimalField("ढिलाइ हर्जाना — प्रतिदिन % (सम्झौता रकमको)", max_digits=6, decimal_places=3,
                                          default=Decimal("0.05"))
    ld_max_pct = models.DecimalField("ढिलाइ हर्जाना — अधिकतम %", max_digits=6, decimal_places=2, default=Decimal("10"))
    variation_office_pct = models.DecimalField("भेरिएसन — कार्यालय प्रमुखले स्वीकृत गर्न सक्ने कुल %", max_digits=6,
                                               decimal_places=2, default=Decimal("15"))
    extension_notice_days = models.PositiveIntegerField("म्याद थप निवेदन — म्याद सकिनुभन्दा कम्तीमा (दिन) अघि", default=21)
    max_running_contracts = models.PositiveIntegerField("एउटा फर्मले एकैपटक लिन पाउने चालु ठेक्का (० = सीमा छैन)", default=0)
    # बाह्य जाँच
    rev_late_fee_pct = models.DecimalField("राजस्व किस्ता: विलम्ब शुल्क (% प्रति महिना)", max_digits=5, decimal_places=2, default=0)
    rev_reminder_days = models.PositiveIntegerField("किस्ता म्याद आउन यति दिन बाँकी हुँदा सम्झाउने", default=7)
    rev_sign_days = models.PositiveIntegerField("स्वीकृत बोलपत्रदाताले सम्झौता गर्ने म्याद (दिन)", default=7)
    rev_portal = models.BooleanField("राजस्व ठेक्का: अनलाइन बोलपत्र खुला", default=False)
    citizen_portal = models.BooleanField("नागरिकका लागि योजना विवरण पेज खुला", default=False)
    field_max_distance = models.PositiveIntegerField("साइट फोटो: योजना स्थलबाट अधिकतम दूरी (मिटर)", default=1000)
    ird_lookup_enabled = models.BooleanField("IRD बाट PAN विवरण ल्याउने", default=False)
    ird_page_url = models.CharField(max_length=250, default="https://ird.gov.np/pan-search")
    ird_api_url = models.CharField(max_length=250, default="https://ird.gov.np/statstics/getPanSearch")
    ppmo_imported_at = models.DateTimeField("PPMO कालोसूची आयात मिति", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        obj = cls.objects.order_by("id").first()
        return obj or cls.objects.create()


class ProcurementPlan(models.Model):
    """एउटा योजनाको खरिद योजना: प्रकृति, विधि, अनुमानित लागत, समयतालिका र स्वीकृति."""
    NATURES = (("works", "निर्माण कार्य"), ("goods", "मालसामान"), ("consulting", "परामर्श सेवा"), ("services", "अन्य सेवा"))
    STATUS = (("draft", "तयार (स्वीकृत हुन बाँकी)"), ("approved", "स्वीकृत"))
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="procurement_plan")
    nature = models.CharField("खरिदको प्रकृति", max_length=20, choices=NATURES, default="works")
    method = models.CharField("खरिद विधि", max_length=20)
    estimated_cost = models.DecimalField("अनुमानित लागत", max_digits=16, decimal_places=2)
    multi_year = models.BooleanField("बहुवर्षीय", default=False)
    grounds = models.JSONField("आधार / शर्त", default=list, blank=True)
    justification = models.TextField("औचित्य", blank=True)
    estimate_date = models.DateField("लागत अनुमान स्वीकृत (लक्ष्य)", null=True, blank=True)
    notice_date = models.DateField("सूचना / आह्वान (लक्ष्य)", null=True, blank=True)
    contract_date = models.DateField("सम्झौता (लक्ष्य)", null=True, blank=True)
    completion_date = models.DateField("काम सम्पन्न (लक्ष्य)", null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_ref = models.CharField("स्वीकृत निर्णय नं. / मिति", max_length=150, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"खरिद योजना – {self.project.name}"



# ================= सोझै खरिद / अमानत / संस्था-समिति कार्यप्रवाह =================
class MinorProcurement(models.Model):
    """सोझै खरिद, अमानत र संस्था/समिति मार्फतको खरिद — एउटै ढाँचा (projects/minor.py)."""
    METHODS = (("direct", "सोझै खरिद"), ("amanat", "अमानत"), ("sanstha", "संस्था / समिति"))
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="minor")
    method = models.CharField(max_length=20, choices=METHODS)
    # लागत अनुमान
    estimate_amount = models.DecimalField("लागत अनुमान", max_digits=16, decimal_places=2)
    estimate_date = models.DateField("लागत अनुमान स्वीकृत मिति")
    estimate_doc = models.FileField("लागत अनुमान (स्क्यान)", upload_to="minor/", null=True, blank=True)
    # सूचना / दरभाउ माग
    notice_date = models.DateField("सूचना / दरभाउ माग मिति", null=True, blank=True)
    notice_ref = models.CharField("सूचना / पत्र संख्या", max_length=150, blank=True)
    # संस्था / समिति: दरभाउपत्र जस्तै आह्वान → प्रस्ताव खोल्ने
    NOTICE_KINDS = (("letter", "सूचीकृत संस्थालाई पत्र"), ("public", "सार्वजनिक सूचना / आशयपत्र (EOI)"),
                    ("both", "सार्वजनिक सूचना र संस्थालाई पत्र"))
    notice_kind = models.CharField("आह्वानको तरिका", max_length=10, choices=NOTICE_KINDS, blank=True, default="")
    submission_deadline = models.DateField("प्रस्ताव पेश गर्ने अन्तिम मिति", null=True, blank=True)
    opening_date = models.DateField("प्रस्ताव खोलेको मिति", null=True, blank=True)
    invited = models.ManyToManyField("quatation.Suchikrit", blank=True, related_name="minor_invites")
    scope = models.TextField("कार्यक्षेत्र / कार्यविवरण (ToR)", blank=True)
    pass_mark = models.DecimalField("प्राविधिक मूल्याङ्कनको न्यूनतम अङ्क", max_digits=5, decimal_places=2, null=True, blank=True)
    # छनौट स्वीकृति
    selected = models.ForeignKey("MinorQuote", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    approver_name = models.CharField(max_length=150, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_remarks = models.TextField(blank=True)
    # आदेश / कार्यादेश / सम्झौता
    order_no = models.CharField("आदेश / सम्झौता नं.", max_length=100, blank=True)
    order_date = models.DateField("आदेश / सम्झौता मिति", null=True, blank=True)
    order_amount = models.DecimalField("आदेश / सम्झौता रकम", max_digits=16, decimal_places=2, null=True, blank=True)
    due_date = models.DateField("काम सम्पन्न / आपूर्ति गर्नुपर्ने मिति", null=True, blank=True)
    in_charge = models.CharField("जिम्मेवार कर्मचारी (अमानत)", max_length=150, blank=True)
    cost_share = models.DecimalField("संस्थाको लागत सहभागिता", max_digits=16, decimal_places=2, null=True, blank=True)
    # सम्पन्न / जाँचपास
    completed_on = models.DateField("सम्पन्न / आपूर्ति मिति", null=True, blank=True)
    completion_value = models.DecimalField("जाँचपास / मूल्याङ्कन रकम", max_digits=16, decimal_places=2, null=True, blank=True)
    completion_note = models.TextField("जाँचपास / प्रतिवेदन", blank=True)
    completion_doc = models.FileField("जाँचपास प्रतिवेदन (स्क्यान)", upload_to="minor/", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_method_display()} – {self.project.name}"


class MinorQuote(models.Model):
    """दरभाउ (सोझै खरिद) वा प्रस्ताव (संस्था/समिति)."""
    minor = models.ForeignKey(MinorProcurement, on_delete=models.CASCADE, related_name="quotes")
    name = models.CharField("फर्म / संस्था", max_length=200)
    firm = models.ForeignKey("quatation.Suchikrit", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="minor_quotes")
    pan = models.CharField("PAN / दर्ता नं.", max_length=50, blank=True)
    address = models.CharField("ठेगाना", max_length=200, blank=True)
    amount = models.DecimalField("कबोल / प्रस्तावित रकम", max_digits=16, decimal_places=2)
    received_on = models.DateField("प्राप्त मिति", null=True, blank=True)
    remarks = models.CharField("कैफियत", max_length=250, blank=True)
    tech_score = models.DecimalField("प्राविधिक अङ्क", max_digits=5, decimal_places=2, null=True, blank=True)
    qualified = models.BooleanField("योग्य (रेस्पोन्सिभ)", default=True)

    class Meta:
        ordering = ["amount", "id"]

    def __str__(self):
        return f"{self.name} ({self.amount})"


class MinorPayment(models.Model):
    """भुक्तानी: किस्ता / हाजिरी (मस्टररोल) / सामग्री / अन्तिम."""
    KINDS = (("running", "किस्ता / चालु बिल"), ("muster", "हाजिरी (मस्टररोल)"), ("material", "सामग्री बिल"),
             ("final", "अन्तिम भुक्तानी"))
    minor = models.ForeignKey(MinorProcurement, on_delete=models.CASCADE, related_name="payments")
    kind = models.CharField(max_length=20, choices=KINDS)
    date = models.DateField("भुक्तानी मिति")
    bill_no = models.CharField("बिल / भौचर नं.", max_length=100, blank=True)
    gross = models.DecimalField("कुल रकम", max_digits=16, decimal_places=2)
    taxes = models.JSONField("कट्टी", default=dict, blank=True)
    net = models.DecimalField("खुद भुक्तानी", max_digits=16, decimal_places=2)
    workers = models.PositiveIntegerField("कामदार संख्या", null=True, blank=True)
    person_days = models.DecimalField("जम्मा श्रम दिन", max_digits=10, decimal_places=1, null=True, blank=True)
    doc = models.FileField("बिल / हाजिरी (स्क्यान)", upload_to="minor/", null=True, blank=True)
    remarks = models.CharField("कैफियत", max_length=250, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]


class MinorPrint(models.Model):
    DOCS = (("invite_tippani", "आह्वान टिप्पणी"), ("invite_letter", "आह्वान पत्र / सूचना"),
            ("approval", "छनौट / स्वीकृति टिप्पणी"), ("order", "आदेश / कार्यादेश / सम्झौता"), ("work_order", "कार्यादेश"),
            ("installment", "किस्ता भुक्तानी टिप्पणी"), ("payment", "भुक्तानी टिप्पणी"))
    minor = models.ForeignKey(MinorProcurement, on_delete=models.CASCADE, related_name="prints")
    doc_type = models.CharField(max_length=20, choices=DOCS)
    printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    printed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["printed_at"]


# ================= नापी किताब (BOQ र नापजाँच) =================
class BOQItem(models.Model):
    """परिमाण सूची (BOQ) को एउटा काम — सम्झौता / लागत अनुमानको परिमाण र दर."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="boq_items")
    sn = models.CharField("क्र.सं.", max_length=20, blank=True)
    description = models.TextField("कामको विवरण")
    unit = models.CharField("एकाइ", max_length=30)
    quantity = models.DecimalField("परिमाण (BOQ)", max_digits=14, decimal_places=3)
    rate = models.DecimalField("दर", max_digits=14, decimal_places=2)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    @property
    def amount(self):
        return (self.quantity * self.rate).quantize(Decimal("0.01"))

    def __str__(self):
        return f"{self.sn} {self.description[:40]}"


class Measurement(models.Model):
    """नापी: संख्या × लम्बाइ × चौडाइ × उचाइ (खाली आयाम छोडिन्छ) वा सिधै परिमाण; घटाउ ऋणात्मक."""
    item = models.ForeignKey(BOQItem, on_delete=models.CASCADE, related_name="measurements")
    date = models.DateField("नापी मिति")
    location = models.CharField("स्थान / चेनेज", max_length=150, blank=True)
    nos = models.DecimalField("संख्या", max_digits=10, decimal_places=3, null=True, blank=True)
    length = models.DecimalField("लम्बाइ", max_digits=12, decimal_places=3, null=True, blank=True)
    breadth = models.DecimalField("चौडाइ", max_digits=12, decimal_places=3, null=True, blank=True)
    height = models.DecimalField("उचाइ / गहिराइ", max_digits=12, decimal_places=3, null=True, blank=True)
    quantity = models.DecimalField("परिमाण", max_digits=14, decimal_places=3)
    deduction = models.BooleanField("घटाउ", default=False)
    remarks = models.CharField("कैफियत", max_length=250, blank=True)
    bill_no = models.PositiveIntegerField("बिल नं.", null=True, blank=True)
    measured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]

    @property
    def signed_quantity(self):
        return -self.quantity if self.deduction else self.quantity



class PPMOBlacklist(models.Model):
    """सार्वजनिक खरिद अनुगमन कार्यालय (PPMO) को कालोसूची — blacklist.ppmo.gov.np बाट आयात."""
    name = models.CharField("फर्म / कम्पनी", max_length=250)
    name_key = models.CharField(max_length=250, db_index=True)
    pan = models.CharField("PAN / दर्ता नं.", max_length=20, blank=True, db_index=True)
    address = models.CharField("ठेगाना", max_length=250, blank=True)
    from_date = models.DateField("देखि", null=True, blank=True)
    to_date = models.DateField("सम्म", null=True, blank=True)
    reason = models.TextField("कारण", blank=True)
    decision = models.CharField("निर्णय / सूचना", max_length=200, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def active(self):
        from datetime import date

        return self.to_date is None or self.to_date >= date.today()


# ================= राजस्व आम्दानी (राजस्व ठेक्का) =================
class RevenueSource(models.Model):
    """राजस्व स्रोत र त्यसको ठेक्का — एक आ.व. को एउटा रेकर्ड (projects/revenue.py मा चरण)."""
    CATEGORIES = (("riverbed", "नदीजन्य पदार्थ (ढुङ्गा, गिट्टी, बालुवा)"), ("parking", "पार्किङ शुल्क"), ("haat", "हाटबजार"),
                  ("toilet", "सार्वजनिक शौचालय"), ("advert", "विज्ञापन / होर्डिङ बोर्ड"), ("ferry", "डुङ्गा / फेरी सेवा"),
                  ("other", "अन्य"))
    ENV_TYPES = (("", "—"), ("bes", "संक्षिप्त वातावरणीय अध्ययन (BES)"), ("iee", "प्रारम्भिक वातावरणीय परीक्षण (IEE)"),
                 ("eia", "वातावरणीय प्रभाव मूल्याङ्कन (EIA)"))
    STATUS = (("active", "सक्रिय"), ("inactive", "निष्क्रिय"), ("completed", "सम्पन्न"), ("cancelled", "सम्झौता रद्द"))
    fiscalyear = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name="revenue_sources")
    previous = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="followers")
    tender_round = models.PositiveIntegerField("बोलपत्र आह्वान पटक", default=1)
    name = models.CharField("राजस्व स्रोत", max_length=250)
    category = models.CharField("प्रकार", max_length=20, choices=CATEGORIES)
    ward = models.ForeignKey("accounts.Ward", on_delete=models.SET_NULL, null=True, blank=True)
    location = models.CharField("स्थान", max_length=250, blank=True)
    boundary = models.TextField("सीमाना / क्षेत्र", blank=True)
    unit = models.CharField("एकाइ", max_length=30, blank=True, default="")
    description = models.TextField("विवरण", blank=True)
    contract_months = models.PositiveIntegerField("ठेक्का अवधि (महिना)", default=12)
    status = models.CharField(max_length=10, choices=STATUS, default="active")
    # प्राविधिक सर्वेक्षण
    survey_date = models.DateField(null=True, blank=True)
    surveyor = models.CharField("सर्वेक्षण गर्ने", max_length=200, blank=True)
    survey_quantity = models.DecimalField("उपलब्ध परिमाण", max_digits=16, decimal_places=2, null=True, blank=True)
    permitted_area = models.TextField("उत्खनन / सञ्चालन गर्न अनुमति क्षेत्र", blank=True)
    env_type = models.CharField("वातावरणीय अध्ययन", max_length=5, choices=ENV_TYPES, blank=True, default="")
    env_ref = models.CharField("वातावरणीय स्वीकृति निर्णय / पत्र", max_length=200, blank=True)
    env_approved_on = models.DateField(null=True, blank=True)
    env_valid_until = models.DateField(null=True, blank=True)
    survey_remarks = models.TextField(blank=True)
    # राजस्व मूल्याङ्कन
    est_quantity = models.DecimalField("अनुमानित परिमाण", max_digits=16, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField("दर", max_digits=14, decimal_places=2, null=True, blank=True)
    est_revenue = models.DecimalField("अनुमानित राजस्व", max_digits=16, decimal_places=2, null=True, blank=True)
    min_bid = models.DecimalField("न्यूनतम कबोल अङ्क", max_digits=16, decimal_places=2, null=True, blank=True)
    estimate_date = models.DateField(null=True, blank=True)
    estimate_note = models.TextField("दरको आधार / हिसाब", blank=True)
    # प्रशासनिक स्वीकृति
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approver_name = models.CharField(max_length=200, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_ref = models.CharField("निर्णय नं.", max_length=150, blank=True)
    approval_remarks = models.TextField(blank=True)
    returned_remarks = models.TextField("फिर्ता गरिएको कारण", blank=True)
    # बोलपत्र आह्वान
    notice_date = models.DateField(null=True, blank=True)
    bid_deadline = models.DateField(null=True, blank=True)
    notice_ref = models.CharField("सूचना नं.", max_length=150, blank=True)
    bid_security_pct = models.DecimalField("बोलपत्र जमानत (%)", max_digits=5, decimal_places=2, default=2.5)
    conditions = models.TextField("योग्यता र शर्त", blank=True)
    opening_date = models.DateField(null=True, blank=True)
    # सफल बोलपत्रदाता
    selected = models.ForeignKey("RevenueBid", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    award_approver = models.CharField(max_length=200, blank=True)
    award_at = models.DateTimeField(null=True, blank=True)
    award_remarks = models.TextField(blank=True)
    # सम्झौता
    agreement_no = models.CharField(max_length=100, blank=True)
    agreement_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    contract_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    security_amount = models.DecimalField("कार्यसम्पादन जमानत", max_digits=16, decimal_places=2, null=True, blank=True)
    security_ref = models.CharField("जमानत (बैंक / नं.)", max_length=200, blank=True)
    security_expiry = models.DateField(null=True, blank=True)
    # फरफारक
    settled_on = models.DateField(null=True, blank=True)
    settlement_remarks = models.TextField(blank=True)
    security_released = models.BooleanField(default=False)
    # सम्झौता रद्द
    cancelled_on = models.DateField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    cancel_ref = models.CharField(max_length=150, blank=True)
    security_forfeited = models.BooleanField(default=False)
    arrears = models.DecimalField("बक्यौता (असुल गर्न बाँकी लगत)", max_digits=16, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.name


class RevenueBid(models.Model):
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="bids")
    firm = models.ForeignKey("quatation.Suchikrit", on_delete=models.SET_NULL, null=True, blank=True, related_name="revenue_bids")
    name = models.CharField("बोलपत्रदाता", max_length=250)
    pan = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=250, blank=True)
    amount = models.DecimalField("कबोल अङ्क", max_digits=16, decimal_places=2)
    security_ok = models.BooleanField("बोलपत्र जमानत ठीक", default=True)
    eligible = models.BooleanField("योग्य / कागजात पुगेको", default=True)
    remarks = models.CharField(max_length=250, blank=True)
    round = models.PositiveIntegerField(default=1)
    online = models.BooleanField("अनलाइन पेश", default=False)
    defaulted = models.BooleanField("स्वीकृतपछि सम्झौता नगरेको", default=False)
    # बोलपत्र जमानत
    SEC_KINDS = (("", "—"), ("cash", "नगद धरौटी"), ("bank", "बैंक जमानत"))
    SEC_STATUS = (("held", "राखिएको"), ("returned", "फिर्ता"), ("forfeited", "जफत"))
    security_kind = models.CharField(max_length=10, choices=SEC_KINDS, blank=True, default="")
    security_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    security_ref = models.CharField("बैंक / जमानत वा रसिद नं.", max_length=200, blank=True)
    security_expiry = models.DateField(null=True, blank=True)
    security_status = models.CharField(max_length=10, choices=SEC_STATUS, default="held")
    security_action_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-amount", "id"]


class RevenueInstalment(models.Model):
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="instalments")
    n = models.PositiveIntegerField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    paid_on = models.DateField(null=True, blank=True)
    receipt_no = models.CharField("रसिद नं.", max_length=100, blank=True)
    remarks = models.CharField(max_length=250, blank=True)
    late_fee_paid = models.DecimalField("विलम्ब शुल्क असुल", max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["n"]


class RevenuePayment(models.Model):
    """एउटा असुली = एउटा रसिद (आंशिक असुली पनि छुट्टै रसिदमा) — SuTRA सँग मिलान यसैबाट."""
    instalment = models.ForeignKey(RevenueInstalment, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    late_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    receipt_no = models.CharField("रसिद नं.", max_length=100, unique=True)
    remarks = models.CharField(max_length=250, blank=True)
    sutra_ok = models.BooleanField("SuTRA मा मिलेको", default=False)
    sutra_checked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]


class RevenueRetender(models.Model):
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="retenders")
    round = models.PositiveIntegerField()
    date = models.DateField()
    reason = models.TextField()
    old_min_bid = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    new_min_bid = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["round"]


class RevenueExtraction(models.Model):
    """नदीजन्य पदार्थको उत्खनन / ढुवानी परिमाण — स्वीकृत (IEE/EIA) परिमाणसँग दाँजिन्छ."""
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="extractions")
    date = models.DateField()
    quantity = models.DecimalField(max_digits=16, decimal_places=2)
    ref = models.CharField("चलान / ढुवानी पुर्जी / अवधि", max_length=200, blank=True)
    remarks = models.CharField(max_length=250, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class RevenueBidder(models.Model):
    """अनलाइन बोलपत्रदाता (कर्मचारी होइन — छुट्टै लगइन; पालिकाको प्रणालीमा पहुँच छैन)."""
    KINDS = (("company", "फर्म / कम्पनी"), ("individual", "व्यक्ति"))
    kind = models.CharField(max_length=12, choices=KINDS, default="company")
    name = models.CharField(max_length=250)
    pan = models.CharField(max_length=20, blank=True)
    reg_no = models.CharField("दर्ता / नागरिकता नं.", max_length=100, blank=True)
    address = models.CharField(max_length=250)
    mobile = models.CharField(max_length=15, unique=True)
    email = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=200)
    reg_doc = models.FileField("दर्ता प्रमाणपत्र", upload_to="revenue/bidders/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class RevenueOnlineBid(models.Model):
    """सिलबन्दी अनलाइन बोलपत्र — कबोल अङ्क सिल (HMAC) गरी राखिन्छ; पेश गर्ने म्याद नसकी कसैले देख्दैन."""
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="online_bids")
    bidder = models.ForeignKey(RevenueBidder, on_delete=models.CASCADE, related_name="bids")
    round = models.PositiveIntegerField(default=1)
    sealed = models.TextField()
    digest = models.CharField(max_length=64)
    security_kind = models.CharField(max_length=10, blank=True)
    security_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    security_ref = models.CharField(max_length=200, blank=True)
    security_doc = models.FileField(upload_to="revenue/bids/", null=True, blank=True)
    doc = models.FileField("कागजात", upload_to="revenue/bids/", null=True, blank=True)
    submitted_at = models.DateTimeField()
    imported = models.BooleanField(default=False)

    class Meta:
        unique_together = [("source", "bidder", "round")]


class RevenueInspection(models.Model):
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="inspections")
    date = models.DateField()
    inspector = models.CharField(max_length=200)
    quantity = models.DecimalField("उत्खनन / सङ्कलन परिमाण", max_digits=16, decimal_places=2, null=True, blank=True)
    finding = models.TextField("निरीक्षणको विवरण")
    violation = models.CharField("उल्लङ्घन", max_length=250, blank=True)
    penalty = models.DecimalField("जरिवाना", max_digits=14, decimal_places=2, default=0)
    action = models.CharField("सुधारात्मक कारबाही", max_length=250, blank=True)
    doc = models.FileField(upload_to="revenue/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class RevenueDoc(models.Model):
    KINDS = (("survey", "सर्वेक्षण प्रतिवेदन"), ("map", "नक्सा"), ("photo", "फोटो"), ("env", "वातावरणीय स्वीकृति"),
             ("agreement", "हस्ताक्षरित सम्झौता"), ("other", "अन्य"))
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="docs")
    kind = models.CharField(max_length=20, choices=KINDS)
    file = models.FileField(upload_to="revenue/")
    created_at = models.DateTimeField(auto_now_add=True)


class RevenuePrint(models.Model):
    source = models.ForeignKey(RevenueSource, on_delete=models.CASCADE, related_name="prints")
    doc_type = models.CharField(max_length=20)
    printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    printed_at = models.DateTimeField(auto_now_add=True)



class YearEndLine(models.Model):
    """आ.व. बन्द गर्दाको योजनाको स्न्यापसट — पछि योजना सरे / बदलिए पनि बन्द प्रतिवेदन यथावत."""
    ACTIONS = (("completed", "सम्पन्न"), ("carried", "क्रमागत — अर्को आ.व. मा सारिएको"), ("frozen", "रोक्का / बजेट फ्रिज"))
    fiscalyear = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="yearend_lines")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="yearend_lines")
    project_name = models.CharField(max_length=250)
    ward_name = models.CharField(max_length=50, blank=True)
    kind_label = models.CharField(max_length=60, blank=True)
    allocated = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    spent = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    committed = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status_label = models.CharField(max_length=60, blank=True)
    action = models.CharField(max_length=10, choices=ACTIONS)
    to_fiscalyear = models.ForeignKey(FiscalYear, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    new_allocation = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    retention_held = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        ordering = ["action", "ward_name", "project_name"]


class NotifySettings(models.Model):
    """SMS / इमेल सूचना — पालिकाअनुसार (एउटा मात्र रेकर्ड)."""
    PROVIDERS = (("", "SMS बन्द"), ("sparrow", "Sparrow SMS"), ("aakash", "Aakash SMS"))
    site_url = models.CharField("प्रणालीको ठेगाना (लिङ्कका लागि)", max_length=200, blank=True)
    # इमेल (SMTP)
    email_on = models.BooleanField("इमेल पठाउने", default=False)
    smtp_host = models.CharField(max_length=150, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_user = models.CharField(max_length=150, blank=True)
    smtp_password = models.CharField(max_length=200, blank=True)
    smtp_tls = models.BooleanField(default=True)
    from_email = models.CharField("पठाउने इमेल", max_length=150, blank=True)
    # SMS
    sms_provider = models.CharField(max_length=10, choices=PROVIDERS, blank=True, default="")
    sms_token = models.CharField("SMS API token", max_length=200, blank=True)
    sms_from = models.CharField("Sender ID (Sparrow)", max_length=30, blank=True)
    # के पठाउने
    staff_digest = models.BooleanField("कर्मचारीलाई दैनिक 'मेरो काम' सारांश", default=True)
    staff_roles = models.CharField(max_length=50, default="2,3,4,7,8")
    staff_sms_urgent = models.BooleanField("जरुरी काम भए मात्र SMS", default=True)
    rev_due_sms = models.BooleanField("राजस्व ठेकेदारलाई किस्ता सम्झाउने", default=True)
    rev_late_sms = models.BooleanField("राजस्व ठेकेदारलाई म्याद नाघेको ताकेता", default=True)
    last_run = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get(cls):
        obj = cls.objects.order_by("id").first()
        return obj or cls.objects.create()


class NotificationLog(models.Model):
    CHANNELS = (("email", "इमेल"), ("sms", "SMS"))
    STATUS = (("sent", "पठाइयो"), ("failed", "असफल"), ("skipped", "पठाइएन"))
    key = models.CharField(max_length=120, db_index=True)
    channel = models.CharField(max_length=6, choices=CHANNELS)
    to = models.CharField(max_length=150)
    name = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=30)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=8, choices=STATUS)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
