"""मेरो काम — पूरा पेज, ड्यासबोर्डको प्यानल (HTMX) र साइडबारको सङ्ख्या."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from .mywork import my_work


@login_required
def my_work_page(request):
    data = my_work(request.user, fresh=request.GET.get("fresh") == "1")
    return render(request, "accounts/my_work.html", {"work": data})


@login_required
def my_work_panel(request):
    data = my_work(request.user, fresh=request.GET.get("fresh") == "1")
    return render(request, "includes/_my_work.html", {"work": data, "compact": True})


@login_required
def my_work_badge(request):
    data = my_work(request.user)
    if not data["total"]:
        return HttpResponse("")
    n = data["total"] if data["total"] < 100 else "99+"
    tone = "bg-rose-500" if data["urgent"] else "bg-amber-500"
    return HttpResponse(f'<span class="ml-auto min-w-[1.25rem] px-1.5 rounded-full {tone} text-white text-[10px] '
                        f'font-bold leading-5 text-center">{n}</span>')


@login_required
def my_work_next(request):
    """साइडबारको तलको कार्ड: अहिलेको खण्डको सबैभन्दा जरुरी बाँकी काम (नभए केही नदेखाउने)."""
    from urllib.parse import urlparse

    from tenants.navigation import PATH_SECTION

    section = request.GET.get("section", "")
    items = my_work(request.user)["items"]

    def sec_of(url):
        path = urlparse(url).path
        for prefix, key in PATH_SECTION:
            if path.startswith(prefix):
                return key
        return "main"

    mine = [i for i in items if section == "main" or sec_of(i["url"]) == section]
    if not mine:
        return HttpResponse("")
    i = mine[0]
    more = len(mine) - 1
    from django.utils.html import escape
    np = str.maketrans("0123456789", "०१२३४५६७८९")
    return HttpResponse(
        '<div class="rounded-lg border border-[#b9c3ff]/60 bg-[#f1f3ff] p-2.5 space-y-2">'
        '<div class="flex items-start gap-1.5"><i data-lucide="info" class="w-4 h-4 text-[#2856eb] mt-0.5 shrink-0"></i>'
        f'<div class="text-[12px] leading-snug"><p class="font-semibold text-slate-800">अर्को काम:</p>'
        f'<p class="text-slate-600">{escape(i["label"])} — {str(i["count"]).translate(np)}</p>'
        + (f'<p class="text-slate-400 mt-0.5">अरू {str(more).translate(np)} काम</p>' if more else "") +
        '</div></div>'
        f'<a href="{escape(i["url"])}" class="block w-full text-center py-1.5 rounded-md text-[12px] font-semibold text-white" '
        'style="background:#2856eb">यहाँबाट सुरु गर्नुहोस्</a></div>'
        '<script>if(window.lucide)lucide.createIcons();</script>')
