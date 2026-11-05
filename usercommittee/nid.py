"""राष्ट्रिय परिचयपत्र (NID) नम्बरबाट व्यक्तिको विवरण खोज्ने।

NID ढाँचा: XXX-XXXX-XX (९ अङ्क), जस्तै 435-6756-65।

NID प्रणाली — .env को NID_API_URL अनुसार:
     NID_API_URL=demo                                       → भित्रै डेमो data (server चाहिँदैन)
     NID_API_URL=http://127.0.0.1:8765/api/person/{nid}/    → `manage.py nid_demo_server`
     NID_API_URL=https://<सरकारी API>/.../{nid}/             → वास्तविक प्रणाली
   वास्तविक API को response ढाँचा फरक भए `_person_from` को field mapping मात्र मिलाउनुहोस्।
पहिले यही पालिकाको व्यक्ति अभिलेख (Person) हेरिन्छ — भेटिए कागजात सहित आउँछ,
फेरि माग्नु पर्दैन। नभेटिए मात्र NID प्रणालीमा सोधिन्छ।
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from . import nid_demo
from .nid_demo import NID_DIGITS, digits as normalize, fmt as format_nid  # noqa: F401  (अरूले यहीँबाट import गर्छन्)

log = logging.getLogger(__name__)


def api_mode():
    url = (getattr(settings, "NID_API_URL", "") or "").strip()
    if not url:
        return ""
    return "demo" if url.lower() == "demo" else "api"


def api_configured():
    return bool(api_mode())


def is_valid(nid):
    return len(normalize(nid)) == NID_DIGITS


_GENDER = {"male": "पुरुष", "m": "पुरुष", "पुरुष": "पुरुष", "female": "महिला", "f": "महिला", "महिला": "महिला",
           "other": "अन्य", "o": "अन्य", "third gender": "अन्य", "अन्य": "अन्य", "तेस्रो लिङ्गी": "अन्य"}


def _gender(v):
    """API को लिङ्ग (Male/F/महिला…) -> फारमको महिला/पुरुष/अन्य."""
    return _GENDER.get(str(v).strip().lower(), "")


def _person_from(data):
    """API को `data` लाई फारमका field मा बदल्ने।"""
    name = data.get("full_name_np") or data.get("name_np") or data.get("full_name") or data.get("name")
    if not name:
        return None
    address = data.get("address_np") or data.get("permanent_address") or data.get("address") or ""
    if isinstance(address, dict):
        address = ", ".join(str(v) for v in address.values() if v)
    return {
        "name": name,
        "address": address,
        "mobile": data.get("mobile") or data.get("phone") or "",
        "citizenship": data.get("citizenship_no") or data.get("citizenship") or "",
        "gender": _gender(data.get("gender") or data.get("sex") or ""),
        "name_en": data.get("full_name_en") or "",
    }


def _from_api(nid):
    """(person | None, error_message | None)."""
    if api_mode() == "demo":
        status, body = nid_demo.api_response(nid)
    else:
        url = settings.NID_API_URL
        nid_q = format_nid(nid)
        url = url.replace("{nid}", urllib.parse.quote(nid_q)) if "{nid}" in url else \
            url + ("&" if "?" in url else "?") + urllib.parse.urlencode({"nid": nid_q})
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        key = getattr(settings, "NID_API_KEY", "")
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=getattr(settings, "NID_API_TIMEOUT", 8)) as r:
                status, body = r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                body = {}
    if status == 404:
        return None, None
    if status == 401:
        return None, "NID प्रणालीले API key स्वीकार गरेन।"
    if status != 200:
        return None, (body or {}).get("message") or f"NID प्रणालीबाट त्रुटि ({status})"
    data = body.get("data", body) if isinstance(body, dict) else {}
    return _person_from(data or {}), None


def registry_person(person):
    """व्यक्ति अभिलेखको व्यक्ति -> फारमलाई चाहिने dict (कागजातका सुरक्षित link सहित)."""
    from django.urls import reverse

    from .roster import DOC_KINDS, POST_LABEL

    last = person.memberships.select_related("committee").order_by("-id").first()
    return {
        "person_id": person.id,
        "name": person.name, "address": person.address, "mobile": person.mobile,
        "citizenship": person.citizenship_no, "gender": person.gender,
        "docs": {k: reverse("uc_person_doc", args=[person.id, k]) for k, _ in DOC_KINDS if person.doc(k)},
        "docs_pdf": [k for k, _ in DOC_KINDS if person.doc(k) and person.doc(k).name.lower().endswith(".pdf")],
        "docs_complete": person.docs_complete,
        "committee": last.committee.name if last else "",
        "post_label": POST_LABEL.get(last.post, "सदस्य") if last else "",
    }


def _from_registry(nid):
    from .roster import find_person

    p = find_person(nid=nid)
    return registry_person(p) if p else None


def lookup(raw):
    nid = normalize(raw)
    mode = api_mode()
    out = {"nid": format_nid(nid), "found": False, "api": bool(mode), "mode": mode}
    if len(nid) != NID_DIGITS:
        out["message"] = "NID ९ अङ्कको हुनुपर्छ (उदाहरण: 435-6756-65)।"
        return out
    # १. यही पालिकाको व्यक्ति अभिलेख (कागजात सहित)
    person = _from_registry(nid)
    if person:
        # अभिलेखमा नभएका विवरण (जस्तै पुराना व्यक्तिको लिङ्ग) NID प्रणालीबाट भर्ने
        blanks = [k for k in ("gender", "address", "mobile", "citizenship") if not person.get(k)]
        if blanks and mode:
            try:
                extra, _err = _from_api(nid)
            except Exception as exc:
                log.warning("NID API lookup failed: %s", exc)
                extra = None
            for k in blanks:
                if extra and extra.get(k):
                    person[k] = extra[k]
        return out | {"found": True, "source": "registry", "person": person}
    # २. NID प्रणाली (डेमो वा वास्तविक)
    if mode:
        try:
            person, err = _from_api(nid)
        except Exception as exc:  # API बन्द भए पनि local खोजी चलोस्
            log.warning("NID API lookup failed: %s", exc)
            person, err = None, "NID प्रणालीमा जोडिन सकिएन।"
        if person:
            return out | {"found": True, "source": "demo" if mode == "demo" else "nid", "person": person}
        if err:
            out["api_error"] = err
    out["message"] = (out.get("api_error") + " " if out.get("api_error") else "") + \
        "यो NID को विवरण भेटिएन, हातैले भर्नुहोस्।"
    return out
