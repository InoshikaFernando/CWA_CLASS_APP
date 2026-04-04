from django.contrib import admin
from .models import HelpCategory, HelpArticle, HelpArticleRole, FAQ


class HelpArticleRoleInline(admin.TabularInline):
    model = HelpArticleRole
    extra = 1


@admin.register(HelpCategory)
class HelpCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'order', 'is_active', 'created_at')
    list_editable = ('order', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(HelpArticle)
class HelpArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'module', 'is_published', 'is_featured', 'order', 'updated_at')
    list_editable = ('order', 'is_published', 'is_featured')
    list_filter = ('is_published', 'is_featured', 'category', 'module')
    search_fields = ('title', 'body_markdown', 'excerpt')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('created_at', 'updated_at')
    inlines = [HelpArticleRoleInline]
    fieldsets = (
        ('Content', {
            'fields': ('title', 'slug', 'category', 'excerpt', 'body_markdown'),
        }),
        ('Targeting', {
            'fields': ('module', 'page_url_name', 'order', 'is_published', 'is_featured'),
            'description': 'Control which pages and roles see this article.',
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'role_group', 'category', 'order', 'is_published')
    list_editable = ('order', 'is_published')
    list_filter = ('role_group', 'category', 'is_published')
    search_fields = ('question', 'answer_markdown')
