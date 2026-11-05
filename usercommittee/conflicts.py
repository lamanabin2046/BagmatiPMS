"""एउटै व्यक्ति एकैपटक धेरै सक्रिय उपभोक्ता समितिमा पदाधिकारी (अध्यक्ष, सचिव, कोषाध्यक्ष) भए चेतावनी।

"सक्रिय" समिति = काम सम्पन्न (status 2) नभएको र हस्तान्तरण पत्र नछापिएको।
पालिकाको सेटिङ (officer_conflict) अनुसार:
  warn  — चेतावनी मात्र (सुरक्षित र स्वीकृत गर्न मिल्छ)
  block — समिति सुरक्षित गर्न र रुजु/स्वीकृत गर्न रोकिन्छ
"""
from django.db import connection

from .nid_demo import NID_DIGITS, digits as nid_digits
from .roster import OFFICERS, POST_LABEL


def policy():
    return getattr(getattr(connection, "tenant", None), "officer_conflict", "warn") or "warn"


def is_blocking():
    return policy() == "block"


def active_committees():
    from .models import DocumentPrint, UserCommittee

    return (UserCommittee.objects.exclude(status=2)
            .exclude(project__document_prints__doc_type=DocumentPrint.HANDOVER)
            .select_related("project", "project__ward"))


def _item(uc, post):
    return {
        "committee_id": uc.id, "committee": uc.name, "project": uc.project.name,
        "project_id": uc.project_id, "ward": getattr(uc.project.ward, "name", "") if uc.project.ward_id else "",
        "post": post, "post_label": POST_LABEL.get(post, "सदस्य"), "officer": post in OFFICERS,
    }


def person_active_posts(person=None, nid="", citizenship="", exclude_uc_id=None):
    """व्यक्ति अरू कुन-कुन सक्रिय समितिमा कुन पदमा छ: [item...]।
    व्यक्ति अभिलेख (CommitteeMember) र पुराना समितिका पदाधिकारी field (NID/नागरिकता) दुवै हेरिन्छ।"""
    from .models import CommitteeMember

    out, seen = [], set()
    active = active_committees()
    if exclude_uc_id:
        active = active.exclude(id=exclude_uc_id)

    if person is not None and person.pk:
        nid = nid or person.nid
        citizenship = citizenship or person.citizenship_no
        links = (CommitteeMember.objects.filter(person=person, committee__in=active)
                 .select_related("committee", "committee__project", "committee__project__ward"))
        for link in links:
            seen.add(link.committee_id)
            out.append(_item(link.committee, link.post))

    # पुराना समिति (व्यक्ति अभिलेख नबनेका): पदाधिकारीको NID / नागरिकता field बाट
    d = nid_digits(nid or "")
    cz = (citizenship or "").strip()
    if len(d) == NID_DIGITS or cz:
        legacy = active.filter(member_links__isnull=True).exclude(id__in=seen)
        for uc in legacy:
            for post in OFFICERS:
                u_nid = nid_digits(getattr(uc, f"{post}_nid", "") or "")
                u_cz = (getattr(uc, f"{post}_citizenship", "") or "").strip()
                if (len(d) == NID_DIGITS and u_nid == d) or (cz and u_cz == cz):
                    out.append(_item(uc, post))
                    seen.add(uc.id)
                    break
    return out


def roster_conflicts(rows, exclude_uc_id=None):
    """फारम/समितिका row हरूमध्ये यहाँ पदाधिकारी भएका र अर्को सक्रिय समितिमा पनि पदाधिकारी भएका।
    returns [{name, post_label, others: [item...]}]"""
    from .models import Person

    out = []
    for r in rows:
        if r.get("post") not in OFFICERS:
            continue
        person = r.get("person")
        if person is None and r.get("person_id"):
            person = Person.objects.filter(id=r["person_id"]).first()
        if person is None:
            from .roster import find_person
            person = find_person(r.get("nid", ""), r.get("citizenship", ""))
        others = [o for o in person_active_posts(person, r.get("nid", ""), r.get("citizenship", ""), exclude_uc_id)
                  if o["officer"]]
        if others:
            out.append({"name": r.get("name") or (person.name if person else ""),
                        "post_label": POST_LABEL.get(r["post"], ""), "others": others})
    return out


def describe(c):
    """एउटा conflict को एक वाक्य।"""
    where = ", ".join(f"“{o['committee']}” ({o['project']}) मा {o['post_label']}" for o in c["others"])
    return f"{c['name']} ({c['post_label']}) हाल {where} पनि हुनुहुन्छ।"


def messages_for(conflicts):
    return [describe(c) for c in conflicts]
