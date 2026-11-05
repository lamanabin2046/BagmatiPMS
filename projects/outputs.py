"""भौतिक उपलब्धि: फारमका लागि सूचक सूची, फारमबाट सुरक्षित गर्ने, र एकीकृत प्रतिवेदन।

फारमका field:  work_category=<id>   out_<indicator_id>=<परिमाण>  (खाली/० = हटाउने)
"""
from decimal import Decimal, InvalidOperation

EN = str.maketrans("०१२३४५६७८९", "0123456789")


def to_qty(raw):
    """'१२.५' / '12,500' -> Decimal; खाली -> None; गलत -> False."""
    raw = (raw or "").strip().translate(EN).replace(",", "")
    if not raw:
        return None
    try:
        v = Decimal(raw)
    except InvalidOperation:
        return False
    return v if v >= 0 else False


def catalog(project=None):
    """फारमका लागि: [{"cat": WorkCategory, "items": [{"ind":…, "value": …}]}] — सक्रिय सूचक,
    साथै यो योजनामा पहिले भरिएका (निष्क्रिय भए पनि)."""
    from .models import OutputIndicator, ProjectOutput, WorkCategory

    values = {}
    if project is not None and project.pk:
        values = {o.indicator_id: o.quantity for o in ProjectOutput.objects.filter(project=project)}
    inds = OutputIndicator.objects.select_related("category").filter(is_active=True, category__is_active=True)
    if values:
        inds = inds | OutputIndicator.objects.select_related("category").filter(id__in=values.keys())
    groups = {}
    for ind in inds.distinct().order_by("category__sort", "category_id", "sort", "id"):
        groups.setdefault(ind.category_id, {"cat": ind.category, "items": []})["items"].append(
            {"ind": ind, "value": values.get(ind.id)})
    cats = list(WorkCategory.objects.filter(is_active=True))
    for c in cats:   # सूचक नभएका सक्रिय प्रकार पनि dropdown मा
        groups.setdefault(c.id, {"cat": c, "items": []})
    order = {c.id: i for i, c in enumerate(WorkCategory.objects.all())}
    return sorted(groups.values(), key=lambda g: order.get(g["cat"].id, 999))


def parse_outputs(post):
    """returns (category_id or None, {indicator_id: Decimal|None}, errors)"""
    from .models import OutputIndicator, WorkCategory

    errors, values = [], {}
    cat = (post.get("work_category") or "").strip()
    cat_id = int(cat) if cat.isdigit() and WorkCategory.objects.filter(id=int(cat)).exists() else None
    names = dict(OutputIndicator.objects.values_list("id", "name"))
    for key in post:
        if not key.startswith("out_") or not key[4:].isdigit():
            continue
        iid = int(key[4:])
        if iid not in names:
            continue
        q = to_qty(post.get(key))
        if q is False:
            errors.append(f"“{names[iid]}” को परिमाण मिलेन।")
        else:
            values[iid] = q
    return cat_id, values, errors


def save_outputs(project, cat_id, values, user=None):
    """फारमका मान सुरक्षित गर्छ (० वा खाली = हटाउने)। फारममा नआएका सूचक छोइँदैनन्।"""
    from .models import ProjectOutput

    project.work_category_id = cat_id
    project.save(update_fields=["work_category"])
    by = user if getattr(user, "is_authenticated", False) else None
    for iid, q in values.items():
        if q is None or q == 0:
            ProjectOutput.objects.filter(project=project, indicator_id=iid).delete()
        else:
            ProjectOutput.objects.update_or_create(project=project, indicator_id=iid,
                                                   defaults={"quantity": q, "updated_by": by})


def apply_from_post(project, post, user=None):
    """फारममा उपलब्धि section भए सुरक्षित; returns errors (खाली = ठीक)."""
    if "work_category" not in post:
        return []
    cat_id, values, errors = parse_outputs(post)
    if errors:
        return errors
    save_outputs(project, cat_id, values, user)
    return []


def summary_for(project):
    """[(सूचक, परिमाण, एकाइ)] — विवरण/प्रिन्टका लागि."""
    return [(o.indicator.name, o.quantity, o.indicator.unit)
            for o in project.outputs.select_related("indicator").all()]


def report(projects_qs, wards):
    """एकीकृत प्रतिवेदन: [{"cat", "rows": [{"ind", "total", "count", "by_ward": [..], "projects": [(p, q)]}]}]"""
    from collections import defaultdict

    from .models import ProjectOutput

    outs = (ProjectOutput.objects.filter(project__in=projects_qs)
            .select_related("indicator__category", "project__ward", "project__fiscalyear"))
    ward_ids = [w.id for w in wards]
    data = {}
    for o in outs:
        ind = o.indicator
        row = data.setdefault(ind.id, {"ind": ind, "total": Decimal("0"), "projects": [],
                                       "by_ward": defaultdict(lambda: Decimal("0"))})
        row["total"] += o.quantity
        row["projects"].append((o.project, o.quantity))
        row["by_ward"][o.project.ward_id] += o.quantity
    groups = {}
    for row in data.values():
        row["count"] = len(row["projects"])
        row["ward_values"] = [row["by_ward"].get(wid) for wid in ward_ids]
        row["projects"].sort(key=lambda t: (t[0].ward_id or 0, t[0].name))
        cat = row["ind"].category
        groups.setdefault(cat.id, {"cat": cat, "rows": []})["rows"].append(row)
    for g in groups.values():
        g["rows"].sort(key=lambda r: (r["ind"].sort, r["ind"].id))
    return sorted(groups.values(), key=lambda g: (g["cat"].sort, g["cat"].id))
