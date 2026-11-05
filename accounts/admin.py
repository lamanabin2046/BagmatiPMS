from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    CustomUser,
    Cao,
    Engineer,
    PlanningOfficer,
    WadaStaff,
    WardSachib,
    Ward,
)

# ============================
# Custom User Admin
# ============================
@admin.register(CustomUser)
class UserModel(UserAdmin):

    model = CustomUser

    list_display = ('id', 'email', 'user_type', 'is_active', 'is_staff')
    list_filter = ('user_type', 'is_active', 'is_staff')
    search_fields = ('email',)
    ordering = ('email',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Permissions', {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            )
        }),
        ('Other Info', {'fields': ('user_type',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'password1',
                'password2',
                'user_type',
                'is_staff',
                'is_active',
            ),
        }),
    )

# ============================
# Other Models
# ============================
admin.site.register(Cao)
admin.site.register(Engineer)
admin.site.register(PlanningOfficer)
admin.site.register(WadaStaff)
admin.site.register(WardSachib)
admin.site.register(Ward)