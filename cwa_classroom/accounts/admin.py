from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Role, UserRole


class UserRoleInline(admin.TabularInline):
    model = UserRole
    extra = 1
    fk_name = 'user'
    raw_id_fields = ('assigned_by',)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    inlines = [UserRoleInline]
    list_display = ('username', 'email', 'get_roles', 'is_active', 'date_joined')
    list_filter = ('roles', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name')

    fieldsets = UserAdmin.fieldsets + (
        ('Profile', {'fields': ('date_of_birth', 'country', 'region', 'package')}),
    )

    def get_roles(self, obj):
        return ', '.join(obj.roles.values_list('name', flat=True))
    get_roles.short_description = 'Roles'


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'display_name')
