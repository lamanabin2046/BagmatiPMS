"""पुराना data नयाँ संरचनामा:
  - UCApprover (स्वीकृत गर्ने प्रत्यायोजित अधिकृत) -> accounts.UserPermission("uc.approve")
  - समितिका पदाधिकारी/सदस्य (field + members JSON) -> Person + CommitteeMember
"""
import re

from django.db import migrations

NP = str.maketrans("०१२३४५६७८९", "0123456789")
OFFICERS = ("chairman", "treasurer", "secretary")
ORDER = {"chairman": 0, "vice_chairman": 1, "treasurer": 2, "secretary": 3, "member": 4}


def digits(s):
    return re.sub(r"\D", "", (s or "").translate(NP))


def forwards(apps, schema_editor):
    UCApprover = apps.get_model("usercommittee", "UCApprover")
    UserPermission = apps.get_model("accounts", "UserPermission")
    for a in UCApprover.objects.all():
        UserPermission.objects.get_or_create(user_id=a.user_id, perm="uc.approve",
                                             defaults={"granted_by_id": a.granted_by_id})

    UserCommittee = apps.get_model("usercommittee", "UserCommittee")
    Person = apps.get_model("usercommittee", "Person")
    CommitteeMember = apps.get_model("usercommittee", "CommitteeMember")

    by_nid, by_cit = {}, {}

    def person_for(row):
        nd, cit = digits(row.get("nid")), (row.get("citizenship") or "").strip()
        p = (by_nid.get(nd) if nd else None) or (by_cit.get(cit) if cit else None)
        if p is None:
            p = Person.objects.create(name=row["name"], nid=row.get("nid") or "", citizenship_no=cit,
                                      address=row.get("address") or "", mobile=row.get("mobile") or "")
        if nd:
            by_nid[nd] = p
        if cit:
            by_cit[cit] = p
        return p

    for uc in UserCommittee.objects.all().order_by("id"):
        rows = []
        for post in OFFICERS:
            name = getattr(uc, f"{post}_name", "")
            if name:
                rows.append({"post": post, "name": name,
                             **{f: getattr(uc, f"{post}_{f}", "") or "" for f in ("nid", "address", "mobile", "citizenship")}})
        for m in uc.members or []:
            if isinstance(m, dict) and m.get("name"):
                post = m.get("post") if m.get("post") in ORDER and m.get("post") not in OFFICERS else "member"
                rows.append({**m, "post": post})
        rows.sort(key=lambda r: ORDER.get(r["post"], 9))
        seen = set()
        for i, row in enumerate(rows):
            p = person_for(row)
            if p.id in seen:
                continue
            seen.add(p.id)
            CommitteeMember.objects.create(committee=uc, person=p, post=row["post"], sort=i)


class Migration(migrations.Migration):
    dependencies = [
        ("usercommittee", "0012_person_registry"),
        ("accounts", "0007_role_and_user_permissions"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
