from django.contrib import admin
from .models import Source, Post, Analysis, Trade

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'scraping_method', 'request_type', 'api_endpoint', 'api_key_field')
    list_filter = ('scraping_method', 'request_type',)
    search_fields = ('name', 'url', 'description')
    fieldsets = (
        (None, {
            'fields': ('name', 'url', 'description', 'scraping_method', 'request_type', 'request_params')
        }),
        ('API Configuration', {
            'fields': ('api_endpoint', 'api_key_field'),
            'classes': ('collapse',), # Makes this section collapsible
        }),
    )

admin.site.register(Post)
admin.site.register(Analysis)
admin.site.register(Trade)
