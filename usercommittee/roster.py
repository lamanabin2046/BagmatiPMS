"""उपभोक्ता समितिका पदाधिकारी तथा सदस्य (पद dropdown, NID, कागजात).

संरचना:
  Person            — व्यक्तिको स्थायी अभिलेख र कागजात (फेरि आउँदा पुनः प्रयोग)
  CommitteeMember   — कुन समितिमा कुन व्यक्ति कुन पदमा
  UserCommittee का chairman_*/secretary_*/treasurer_* field र `members` JSON —
                      पुराना print/प्रतिवेदनका लागि नाम आदिको प्रतिलिपि (snapshot)
"""
import os

from .nid_demo import NID_DIGITS, digits as nid_digits, fmt as nid_fmt

POSTS = [
    ("chairman", "अध्यक्ष"),
    ("vice_chairman", "उपाध्यक्ष"),
    ("treasurer", "कोषाध्यक्ष"),
    ("secretary", "सचिव"),
    ("member", "सदस्य"),
]
POST_LABEL = dict(POSTS)
POST_ORDER = {k: i for i, (k, _) in enumerate(POSTS)}
OFFICERS = ("chairman", "treasurer", "secretary")  # एक-एक जना अनिवार्य
FIELDS = ("name", "nid", "address", "mobile", "citizenship", "gender")
GENDERS = ["महिला", "पुरुष", "अन्य"]
WOMEN_MIN_PCT = 33  # कम्तीमा ३३% महिला; अध्यक्ष, सचिव, कोषाध्यक्षमध्ये कम्तीमा एक महिला
DOC_KINDS = [
    ("photo", "फोटो"),
    ("citizenship_front", "नागरिकता (अगाडि)"),
    ("citizenship_back", "नागरिकता (पछाडि)"),
    ("nid_card", "राष्ट्रिय परिचयपत्र"),
]
DOC_TYPES = (".jpg", ".jpeg", ".png", ".webp", ".pdf")
DOC_MAX_MB = 5

# नयाँ फारममा सुरुमै देखिने row हरू
DEFAULT_POSTS = ["chairman", "vice_chairman", "treasurer", "secretary", "member", "member"]


def _row(post, **data):
    row = {"post": post, "post_label": POST_LABEL.get(post, "सदस्य")}
    for f in FIELDS:
        v = data.get(f)
        row[f] = v.strip() if isinstance(v, str) else (v or "")
    row["person_id"] = data.get("person_id") or ""
    row["key"] = data.get("key") or ""
    row["docs"] = data.get("docs") or {}          # kind -> True (कागजात छ)
    row["missing"] = data.get("missing") or []
    return row


def person_docs(person):
    return {k: bool(person.doc(k)) for k, _ in DOC_KINDS}


def roster_rows(uc):
    """समितिका सबै सदस्य, पदको क्रममा (print, फारम, स्वीकृत modal)."""
    links = list(uc.member_links.all()) if uc.pk else []
    if links:
        rows = []
        for link in links:
            p = link.person
            rows.append(_row(link.post, name=p.name, nid=p.nid, address=p.address, mobile=p.mobile,
                             citizenship=p.citizenship_no, gender=p.gender, person_id=p.id, docs=person_docs(p),
                             missing=p.missing_docs) | {"person": p})
        rows.sort(key=lambda r: POST_ORDER.get(r["post"], 99))
        return rows

    # व्यक्ति अभिलेख बन्नुअघिका समिति
    rows = []
    for post in OFFICERS:
        name = getattr(uc, f"{post}_name", "") or ""
        if name:
            rows.append(_row(post, name=name, **{f: getattr(uc, f"{post}_{f}", "") or ""
                                                 for f in ("nid", "address", "mobile", "citizenship")}))
    for m in uc.members or []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        post = m.get("post") if m.get("post") in POST_LABEL and m.get("post") not in OFFICERS else "member"
        rows.append(_row(post, **{f: m.get(f, "") for f in FIELDS}))
    rows.sort(key=lambda r: POST_ORDER.get(r["post"], 99))
    for r in rows:
        r["missing"] = ["फोटो", "नागरिकता (दुवै पाटा) वा राष्ट्रिय परिचयपत्र"]
    return rows


def default_rows():
    return [_row(p, key=f"n{i}") for i, p in enumerate(DEFAULT_POSTS)]


def parse_roster(post_data, files=None):
    """फारमको m_post[], m_name[] … र doc_<key>_<kind> फाइलबाट (rows, errors)।"""
    files = files or {}
    lists = {f: post_data.getlist(f"m_{f}") for f in ("post", "person", "key") + FIELDS}
    rows = []
    for i, post in enumerate(lists["post"]):
        data = {f: (lists[f][i] if i < len(lists[f]) else "") for f in FIELDS}
        if not data["name"].strip():
            continue
        if data["nid"].strip():
            data["nid"] = nid_fmt(data["nid"])
        if data["gender"] not in GENDERS:
            data["gender"] = ""
        key = lists["key"][i] if i < len(lists["key"]) else ""
        pid = lists["person"][i] if i < len(lists["person"]) else ""
        row = _row(post if post in POST_LABEL else "member", **data,
                   person_id=int(pid) if str(pid).isdigit() else "", key=key)
        row["uploads"] = {k: files.get(f"doc_{key}_{k}") for k, _ in DOC_KINDS if key and files.get(f"doc_{key}_{k}")}
        rows.append(row)

    errors = []
    bad = [r["name"] for r in rows if r["nid"] and len(nid_digits(r["nid"])) != NID_DIGITS]
    if bad:
        errors.append("NID नम्बर ९ अङ्कको हुनुपर्छ (उदाहरण: 435-6756-65): " + ", ".join(bad))
    for post in OFFICERS:
        n = sum(1 for r in rows if r["post"] == post)
        if n == 0:
            errors.append(f"{POST_LABEL[post]} को नाम अनिवार्य छ।")
        elif n > 1:
            errors.append(f"{POST_LABEL[post]} एक जना मात्र हुनुपर्छ।")
    if sum(1 for r in rows if r["post"] == "vice_chairman") > 1:
        errors.append("उपाध्यक्ष एक जना मात्र हुनुपर्छ।")
    nids = [nid_digits(r["nid"]) for r in rows if r["nid"]]
    if len(nids) != len(set(nids)):
        errors.append("एउटै NID नम्बर दुई जना सदस्यमा राखिएको छ।")
    no_gender = [r["name"] for r in rows if not r["gender"]]
    if no_gender:
        errors.append("लिङ्ग छान्नुहोस्: " + ", ".join(no_gender))
    pids = [r["person_id"] for r in rows if r["person_id"]]
    if len(pids) != len(set(pids)):
        errors.append("एउटै व्यक्ति दुई पटक राखिएको छ।")
    for r in rows:
        for kind, f in r["uploads"].items():
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in DOC_TYPES:
                errors.append(f"{r['name']}: {dict(DOC_KINDS)[kind]} JPG, PNG वा PDF मात्र।")
            elif f.size > DOC_MAX_MB * 1024 * 1024:
                errors.append(f"{r['name']}: {dict(DOC_KINDS)[kind]} {DOC_MAX_MB} MB भन्दा सानो हुनुपर्छ।")
    if any(r["uploads"] for r in rows) and errors:
        errors.append("माथिको गल्ती सच्याएर कागजात फेरि छान्नुहोस् (सुरक्षाका कारण browser ले छानेको फाइल सम्झँदैन)।")
    return rows, errors


def apply_roster(uc, rows):
    """नाम आदिको प्रतिलिपि UserCommittee मा राख्छ (save गर्दैन)।"""
    for post in OFFICERS:
        r = next((x for x in rows if x["post"] == post), None) or _row(post)
        setattr(uc, f"{post}_name", r["name"])
        for f in ("nid", "address", "mobile", "citizenship"):
            setattr(uc, f"{post}_{f}", r[f] or None)
    uc.members = [
        {k: r[k] for k in ("post",) + FIELDS if r[k]}
        for r in rows if r["post"] not in OFFICERS
    ]


def find_person(nid="", citizenship="", person_id=None):
    from .models import Person

    if person_id:
        p = Person.objects.filter(id=person_id).first()
        if p:
            return p
    d = nid_digits(nid)
    if len(d) == NID_DIGITS:
        p = Person.objects.filter(nid=nid_fmt(d)).first()
        if p:
            return p
        for p in Person.objects.exclude(nid=""):
            if nid_digits(p.nid) == d:
                return p
    if citizenship.strip():
        return Person.objects.filter(citizenship_no=citizenship.strip()).first()
    return None


def sync_members(uc, rows, user=None):
    """समिति save भएपछि: व्यक्ति अभिलेख बनाउने/अद्यावधिक गर्ने, कागजात राख्ने, सदस्यता जोड्ने।"""
    from .models import CommitteeMember, Person

    keep = []
    for i, r in enumerate(rows):
        p = find_person(r["nid"], r["citizenship"], r["person_id"])
        if p is None:
            p = Person(created_by=user if getattr(user, "is_authenticated", False) else None)
        p.name = r["name"]
        if r["nid"]:
            p.nid = r["nid"]
        if r["citizenship"]:
            p.citizenship_no = r["citizenship"]
        p.address = r["address"] or p.address
        p.mobile = r["mobile"] or p.mobile
        p.gender = r["gender"] or p.gender
        if p.pk is None:
            p.save()
        old = []
        for kind, f in r.get("uploads", {}).items():
            prev = getattr(p, kind)
            if prev and prev.name:
                old.append((prev.storage, prev.name))
            getattr(p, kind).save(f.name, f, save=False)
        p.save()
        for storage, name in old:
            try:
                storage.delete(name)
            except Exception:
                pass
        CommitteeMember.objects.update_or_create(committee=uc, person=p, defaults={"post": r["post"], "sort": i})
        keep.append(p.id)
    CommitteeMember.objects.filter(committee=uc).exclude(person_id__in=keep).delete()


def committee_doc_problems(uc):
    """स्वीकृतका लागि नपुगेका कागजात: [(post_label, name, [missing...])]."""
    if uc is None:
        return []
    return [(r["post_label"], r["name"], r["missing"]) for r in roster_rows(uc) if r["missing"]]


def with_slots(rows):
    """फारमका लागि: हरेक row मा कागजातका ४ खाना (भएको कागजातको सुरक्षित link सहित)."""
    from django.urls import reverse

    for i, r in enumerate(rows):
        r["key"] = r.get("key") or f"e{i}"
        r["slots"] = []
        for kind, label in DOC_KINDS:
            has = bool(r.get("docs", {}).get(kind)) and r.get("person_id")
            url = reverse("uc_person_doc", args=[r["person_id"], kind]) if has else ""
            p = r.get("person")
            pdf = bool(has and p is not None and p.doc(kind) and p.doc(kind).name.lower().endswith(".pdf"))
            r["slots"].append({"kind": kind, "label": label, "url": url, "pdf": pdf})
    return rows


def gender_summary(rows):
    """महिला सहभागिता: कम्तीमा ३३% महिला र पदाधिकारी (अध्यक्ष/सचिव/कोषाध्यक्ष) मध्ये कम्तीमा एक महिला."""
    total = len(rows)
    women = sum(1 for r in rows if r.get("gender") == "महिला")
    men = sum(1 for r in rows if r.get("gender") == "पुरुष")
    other = sum(1 for r in rows if r.get("gender") == "अन्य")
    unknown = total - women - men - other
    pct = round(women * 100 / total) if total else 0
    officer_woman = any(r.get("gender") == "महिला" for r in rows if r.get("post") in OFFICERS)
    warnings = []
    if total and unknown:
        warnings.append(f"{unknown} जनाको लिङ्ग खुलेको छैन।")
    if total and women * 100 < WOMEN_MIN_PCT * total:
        warnings.append(f"महिला सहभागिता {pct}% मात्र — कम्तीमा {WOMEN_MIN_PCT}% चाहिन्छ।")
    if total and not officer_woman:
        warnings.append("अध्यक्ष, सचिव वा कोषाध्यक्षमध्ये कम्तीमा एक महिला हुनुपर्छ।")
    return {"total": total, "women": women, "men": men, "other": other, "unknown": unknown, "pct": pct,
            "officer_woman": officer_woman, "warnings": warnings, "ok": total > 0 and not warnings}
