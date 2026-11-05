from urllib.parse import parse_qs, urlparse

from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme

SESSION_KEY = "uc_return"


class ReturnToNextMiddleware:
    """After a successful form save, go back to the page the user came from (उपभोक्ता समिति workflow).

    Step buttons on the workflow page open forms as `/some/form/?next=/UserCommittee/Workflow/?open=<id>`.
    When such a form is saved (the view redirects and no error message was added) the user is sent
    to `next` — the workflow page, with that project's panel opened again.

    `next` is found in: the POST field `next`, the Referer's query string, or — when the form was
    re-shown after an error (its URL lost `?next=`) — the session, remembered when the form was opened.
    On errors the view's own response is kept. "delete…" actions inside a page stay on that page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET":
            self._remember(request)
        response = self.get_response(request)
        if request.method != "POST" or not (300 <= response.status_code < 400):
            return response
        if getattr(response, "stay_here", False):     # view ले यही पेजमा बस्न भनेको
            return response
        if (request.POST.get("action") or "").startswith("delete"):
            return response
        queued = getattr(getattr(request, "_messages", None), "_queued_messages", [])
        if any(m.level >= messages.ERROR for m in queued):
            return response
        nxt = request.POST.get("next") or self._from_referer(request) or self._from_session(request)
        if not self._safe(request, nxt):
            return response
        self._forget(request)
        response["Location"] = nxt
        return response

    # ---- helpers ----
    @staticmethod
    def _safe(request, nxt):
        return bool(nxt) and nxt.startswith("/") and "/Accounts/" not in nxt and \
            url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()})

    def _remember(self, request):
        session = getattr(request, "session", None)
        if session is None or request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
            return  # HTMX partials (panel, modal) are not form pages
        nxt = request.GET.get("next")
        stored = session.get(SESSION_KEY)
        if nxt and self._safe(request, nxt):
            session[SESSION_KEY] = {"form": request.path, "next": nxt}
        elif stored and stored.get("form") == request.path and "next" not in request.GET \
                and urlparse(request.META.get("HTTP_REFERER") or "").path != request.path:
            # same form opened again from somewhere else (menu) → don't send it to the workflow
            session.pop(SESSION_KEY, None)

    @staticmethod
    def _from_referer(request):
        ref = request.META.get("HTTP_REFERER") or ""
        if not ref:
            return None
        values = parse_qs(urlparse(ref).query).get("next")
        return values[0] if values else None

    @staticmethod
    def _from_session(request):
        session = getattr(request, "session", None)
        stored = session.get(SESSION_KEY) if session is not None else None
        if not stored:
            return None
        ref_path = urlparse(request.META.get("HTTP_REFERER") or "").path
        if stored.get("form") in (request.path, ref_path):
            return stored.get("next")
        return None

    @staticmethod
    def _forget(request):
        session = getattr(request, "session", None)
        if session is not None:
            session.pop(SESSION_KEY, None)
