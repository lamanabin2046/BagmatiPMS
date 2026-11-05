"""चालु आर्थिक वर्ष — कामकाज यही आ.व. का योजनामा मात्र.

* Admin ले सेटिङ → आर्थिक वर्षबाट "चालु" तोक्छ (FiscalYear.is_current, एउटा मात्र)।
* कार्यप्रवाह, खरिद योजना, बजेट, ड्यासबोर्ड, मेरो काम र नयाँ योजना दर्ता: पूर्वनिर्धारित रूपमा चालु आ.व.।
* अघिल्ला (वा अरू) आ.व. का योजना: हेर्न / छाप्न मात्र — काम (POST) रोकिन्छ, OldFiscalYearLockMiddleware।
  छुट: धरौटी फिर्ता र जमानत (अघिल्ला वर्षका दायित्व)।
* आ.व. बन्द गर्दा बहुवर्षीय योजना मात्र इतिहाससहित नयाँ आ.व. मा सर्छ (projects/yearend.py) र नयाँ आ.व. चालु हुन्छ।
"""
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect

# अघिल्लो आ.व. का योजनामा पनि गर्न मिल्ने काम (url name)
OLD_FY_ALLOWED = {
    "retention_recommend", "retention_release", "retention_tippani",          # धरौटी फिर्ता
    "extend_performance_bond", "add_pg_bank_detail",                          # कार्यसम्पादन जमानत
}
# url मा <id> ले योजना (Project) जनाउने पुराना पेज
PROJECT_ID_URLS = {"edit_project", "delete_project", "add_ward_recommendation", "add_completion_recommendation",
                   "palika_engineer_project_detail"}


def current_fy():
    from .models import FiscalYear

    fy = FiscalYear.objects.filter(is_current=True).first()
    if fy is None:   # तोकिएको छैन भने: बन्द नभएको सबैभन्दा पुरानो, नभए सबैभन्दा नयाँ
        open_ = list(FiscalYear.objects.filter(closed_at__isnull=True).order_by("name"))
        fy = open_[0] if open_ else FiscalYear.objects.order_by("-name").first()
    return fy


def set_current(fy):
    from .models import FiscalYear

    with transaction.atomic():
        FiscalYear.objects.exclude(id=fy.id).filter(is_current=True).update(is_current=False)
        FiscalYear.objects.filter(id=fy.id).update(is_current=True)


def current_fy_id():
    fy = current_fy()
    return fy.id if fy else None


def default_fy_param(request, key="fiscalyear"):
    """सूचीको आ.व. filter: URL मा नभए चालु आ.व. ('' = सबै आ.व., प्रयोगकर्ताले छानेमा)।"""
    if key in request.GET:
        return request.GET.get(key, "")
    cid = current_fy_id()
    return str(cid) if cid else ""


def is_old(project):
    cid = current_fy_id()
    return bool(cid and project is not None and project.fiscalyear_id and project.fiscalyear_id != cid)


def old_message(project):
    fy = getattr(project, "fiscalyear", None)
    cur = current_fy()
    return (f"यो योजना आ.व. {fy.name if fy else ''} को हो — चालु आ.व. {cur.name if cur else ''} होइन। "
            "हेर्न र छाप्न मात्र मिल्छ (धरौटी फिर्ता र जमानत बाहेक)।")


def lock_steps(project, steps):
    """अघिल्लो आ.व. को योजना भए कार्यप्रवाहका बटन हटाउने (छाप्ने / हेर्ने — new_tab — मात्र राख्ने)। True = लक."""
    if not is_old(project):
        return False
    for st in steps:
        if isinstance(st, dict) and st.get("actions"):
            st["actions"] = [a for a in st["actions"] if a.get("new_tab")]
    return True


class OldFiscalYearLockMiddleware:
    """चालु आ.व. बाहेकका योजनामा फारम सुरक्षित (POST) हुन नदिने — सबै कार्यप्रवाहमा एकै ठाउँबाट।"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        match = getattr(request, "resolver_match", None)
        name = getattr(match, "url_name", "") or ""
        if not name or name in OLD_FY_ALLOWED:
            return None
        pid = view_kwargs.get("project_id")
        if pid is None and name in PROJECT_ID_URLS:
            pid = view_kwargs.get("id") or view_kwargs.get("pk")
        if pid is None and name in ("update_project",):
            pid = request.POST.get("project_id")
        if pid is None and name == "field_project":
            pid = view_kwargs.get("pid")
        if pid is None or not str(pid).isdigit():
            return None
        tenant = getattr(request, "tenant", None)
        if tenant is None or getattr(tenant, "schema_name", "public") == "public":
            return None
        from .models import Project

        project = Project.objects.filter(id=pid).select_related("fiscalyear").first()
        if not is_old(project):
            return None
        msg = old_message(project)
        if request.headers.get("HX-Request"):
            return HttpResponse(f'<div class="rounded-lg border border-amber-300 bg-amber-50 text-amber-800 text-sm px-3 py-2">'
                                f'<i class="fas fa-lock"></i> {msg}</div>', status=403)
        messages.error(request, msg)
        return redirect(request.META.get("HTTP_REFERER") or "/")
