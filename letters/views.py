import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import has_perm

from .models import LetterOverride, LetterTemplate
from .sanitize import clean_html

MAX_HTML = 300_000


def _payload(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}


@login_required
@require_POST
def save(request):
    """{scope: letter|template, key, ref, title, html}"""
    d = _payload(request)
    scope, key = d.get("scope"), (d.get("key") or "")[:80]
    html = d.get("html") or ""
    if not key or len(html) > MAX_HTML:
        return JsonResponse({"ok": False, "message": "पत्र धेरै लामो वा अपूरो छ।"}, status=400)
    html = clean_html(html)
    if not html.strip():
        return JsonResponse({"ok": False, "message": "पत्र खाली छ।"}, status=400)
    if scope == "template":
        if not has_perm(request.user, "letters.templates"):
            return JsonResponse({"ok": False, "message": "ढाँचा बदल्ने अनुमति छैन।"}, status=403)
        LetterTemplate.objects.update_or_create(key=key, defaults={
            "html": html, "title": (d.get("title") or "")[:200], "updated_by": request.user})
        # ढाँचा बदलेपछि यो पत्रको छुट्टै सम्पादन रहे त्यो नै देखिन्छ; प्रयोगकर्ताले चाहे हटाउन मिल्छ
        return JsonResponse({"ok": True, "message": "पालिकाको ढाँचा सुरक्षित भयो। अब यस प्रकारका सबै पत्रमा लागू हुन्छ।"})
    if scope == "letter":
        if not has_perm(request.user, "letters.edit"):
            return JsonResponse({"ok": False, "message": "पत्र सम्पादन गर्ने अनुमति छैन।"}, status=403)
        ref = (d.get("ref") or "")[:300]
        if not ref.startswith("/"):
            return JsonResponse({"ok": False, "message": "पत्र चिनिएन।"}, status=400)
        LetterOverride.objects.update_or_create(key=key, ref=ref, defaults={
            "html": html, "title": (d.get("title") or "")[:200], "updated_by": request.user})
        return JsonResponse({"ok": True, "message": "यो पत्रको सम्पादन सुरक्षित भयो।"})
    return JsonResponse({"ok": False, "message": "scope मिलेन।"}, status=400)


@login_required
@require_POST
def reset(request):
    """{scope: letter|template, key, ref} — सम्पादन हटाएर मूल अवस्थामा."""
    d = _payload(request)
    scope, key = d.get("scope"), d.get("key") or ""
    if scope == "template":
        if not has_perm(request.user, "letters.templates"):
            return JsonResponse({"ok": False, "message": "अनुमति छैन।"}, status=403)
        LetterTemplate.objects.filter(key=key).delete()
        return JsonResponse({"ok": True, "message": "पालिकाको ढाँचा हटाइयो, अब मूल ढाँचा प्रयोग हुन्छ।"})
    if scope == "letter":
        if not has_perm(request.user, "letters.edit"):
            return JsonResponse({"ok": False, "message": "अनुमति छैन।"}, status=403)
        LetterOverride.objects.filter(key=key, ref=d.get("ref") or "").delete()
        return JsonResponse({"ok": True, "message": "यो पत्रको सम्पादन हटाइयो।"})
    return JsonResponse({"ok": False, "message": "scope मिलेन।"}, status=400)


@login_required
def templates_list(request):
    """पालिकाका पत्र ढाँचा र सम्पादित पत्रहरूको सूची."""
    if not (has_perm(request.user, "letters.templates") or has_perm(request.user, "letters.edit")):
        return redirect("unauthorized")
    if request.method == "POST" and has_perm(request.user, "letters.templates"):
        get_object_or_404(LetterTemplate, id=request.POST.get("id")).delete()
        messages.success(request, "ढाँचा हटाइयो, अब मूल ढाँचा प्रयोग हुन्छ।")
        return redirect("letter_templates")
    return render(request, "letters/templates_list.html", {
        "templates": LetterTemplate.objects.select_related("updated_by"),
        "overrides": LetterOverride.objects.select_related("updated_by")[:100],
        "can_template": has_perm(request.user, "letters.templates"),
    })
