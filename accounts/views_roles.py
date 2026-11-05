"""भूमिका र अनुमति — Admin ले हरेक भूमिकाको अनुमति र व्यक्तिगत थप अनुमति मिलाउने पेज."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import CustomUser, RolePermission, UserPermission
from .permissions import (DEFAULT_ROLE_PERMS, LOCKED, PERM_CODES, PERM_LABEL, PERMISSIONS, ROLE_LABEL, ROLES,
                          clear_cache, engineer_locked, has_perm, role_perms)


@login_required
def roles_permissions(request):
    if not has_perm(request.user, "settings.roles"):
        return redirect("unauthorized")

    if request.method == "POST" and request.POST.get("form") == "matrix":
        changed = 0
        for role, _label in ROLES:
            current = role_perms(role)
            for code in PERM_CODES:
                if (role, code) in LOCKED or engineer_locked(role, code):
                    continue
                want = f"{role}:{code}" in request.POST
                if want != (code in current):
                    changed += 1
                default = code in DEFAULT_ROLE_PERMS.get(role, set())
                if want == default:
                    RolePermission.objects.filter(role=role, perm=code).delete()
                else:
                    RolePermission.objects.update_or_create(role=role, perm=code,
                                                            defaults={"allowed": want, "updated_by": request.user})
        clear_cache(request.user)
        messages.success(request, f"भूमिकाका अनुमति सुरक्षित भए ({changed} परिवर्तन)।" if changed else "कुनै परिवर्तन थिएन।")
        return redirect("roles_permissions")

    if request.method == "POST" and request.POST.get("form") == "reset":
        RolePermission.objects.all().delete()
        messages.success(request, "सबै भूमिकाका अनुमति सुरुको (default) अवस्थामा फर्काइयो।")
        return redirect("roles_permissions")

    if request.method == "POST" and request.POST.get("form") == "user":
        user = get_object_or_404(CustomUser, id=request.POST.get("user_id"))
        code = request.POST.get("perm", "")
        if request.POST.get("action") == "revoke":
            UserPermission.objects.filter(user=user, perm=code).delete()
            messages.success(request, f"{user.mobile} को “{PERM_LABEL.get(code, code)}” हटाइयो।")
        elif code in PERM_CODES and code != "settings.roles":
            UserPermission.objects.get_or_create(user=user, perm=code, defaults={"granted_by": request.user})
            messages.success(request, f"{user.mobile} लाई “{PERM_LABEL[code]}” अनुमति दिइयो।")
        return redirect("roles_permissions")

    from usercommittee.views_workflow import staff_names

    names = staff_names()
    matrix = {role: role_perms(role) for role, _ in ROLES}
    groups = []
    for code, group, label, help_text in PERMISSIONS:
        if not groups or groups[-1]["name"] != group:
            groups.append({"name": group, "perms": []})
        groups[-1]["perms"].append({
            "code": code, "label": label, "help": help_text,
            "cells": [{"role": role, "on": code in matrix[role], "locked": (role, code) in LOCKED,
                       "eng_off": engineer_locked(role, code),
                       "default": code in DEFAULT_ROLE_PERMS.get(role, set())} for role, _ in ROLES],
        })
    extra = [
        {"up": up, "name": names.get(up.user_id) or up.user.mobile, "role": ROLE_LABEL.get(up.user.user_type, ""),
         "label": PERM_LABEL.get(up.perm, up.perm)}
        for up in UserPermission.objects.select_related("user", "granted_by").order_by("user__user_type", "user_id")
    ]
    users = [{"id": u.id, "name": names.get(u.id) or u.mobile, "mobile": u.mobile, "role": ROLE_LABEL.get(u.user_type, "")}
             for u in CustomUser.objects.filter(is_active=True).order_by("user_type", "id")]
    return render(request, "Admin/Accounts/roles_permissions.html", {
        "roles": ROLES, "groups": groups, "extra": extra, "users": users,
        "grantable": [(c, l) for c, _g, l, _h in PERMISSIONS if c != "settings.roles"],
        "overrides": RolePermission.objects.count(),
    })
