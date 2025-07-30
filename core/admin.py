from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Source, Post, Analysis, Trade, TradingConfig, ApiResponse


@admin.register(TradingConfig)
class TradingConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "default_position_size",
        "stop_loss_percentage",
        "take_profit_percentage",
        "min_confidence_threshold",
    )
    list_filter = (
        "is_active",
        "position_sizing_method",
        "market_hours_only",
        "trading_enabled",
    )
    search_fields = ("name",)

    fieldsets = (
        (
            "Basic Configuration",
            {"fields": ("name", "is_active", "trading_enabled", "market_hours_only")},
        ),
        (
            "Position Sizing",
            {
                "fields": (
                    "position_sizing_method",
                    "default_position_size",
                    "max_position_size",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Risk Management",
            {
                "fields": (
                    "stop_loss_percentage",
                    "take_profit_percentage",
                    "min_confidence_threshold",
                ),
            },
        ),
        (
            "Trading Constraints",
            {
                "fields": ("max_daily_trades",),
                "classes": ("collapse",),
            },
        ),
        (
            "LLM Configuration",
            {
                "fields": ("llm_model", "llm_prompt_template"),
                "classes": ("collapse",),
            },
        ),
    )


class PostInline(admin.TabularInline):
    model = Post
    extra = 0
    readonly_fields = ("content_preview", "url", "created_at")
    fields = ("content_preview", "url", "created_at")

    def content_preview(self, obj):
        return obj.content[:100] + "..." if len(obj.content) > 100 else obj.content

    content_preview.short_description = "Content Preview"


class ApiResponseInline(admin.TabularInline):
    model = ApiResponse
    extra = 0
    readonly_fields = ("url", "created_at", "posts_count")
    fields = ("url", "created_at", "posts_count")

    def posts_count(self, obj):
        return obj.posts.count()

    posts_count.short_description = "Posts"


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "scraping_method",
        "scraping_enabled",
        "scraping_status",
        "last_scraped_at",
        "error_count",
        "posts_count",
    )
    list_filter = (
        "scraping_method",
        "scraping_enabled",
        "scraping_status",
        "request_type",
    )
    search_fields = ("name", "url", "description")
    readonly_fields = (
        "last_scraped_at",
        "error_count",
        "last_error",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("name", "url", "description", "scraping_enabled")},
        ),
        (
            "Scraping Configuration",
            {
                "fields": (
                    "scraping_method",
                    "scraping_interval_minutes",
                    "data_extraction_config",
                )
            },
        ),
        (
            "API Configuration",
            {
                "fields": (
                    "api_endpoint",
                    "api_key_field",
                    "request_type",
                    "request_params",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Status & Monitoring",
            {
                "fields": (
                    "scraping_status",
                    "last_scraped_at",
                    "error_count",
                    "last_error",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [ApiResponseInline, PostInline]

    def posts_count(self, obj):
        count = obj.individual_posts.count()
        url = reverse("admin:core_post_changelist") + f"?source__id__exact={obj.id}"
        return format_html('<a href="{}">{} posts</a>', url, count)

    posts_count.short_description = "Posts"

    actions = ["enable_scraping", "disable_scraping", "reset_error_count"]

    def enable_scraping(self, request, queryset):
        queryset.update(scraping_enabled=True, scraping_status="idle")
        self.message_user(request, f"Enabled scraping for {queryset.count()} sources.")

    enable_scraping.short_description = "Enable scraping"

    def disable_scraping(self, request, queryset):
        queryset.update(scraping_enabled=False, scraping_status="disabled")
        self.message_user(request, f"Disabled scraping for {queryset.count()} sources.")

    disable_scraping.short_description = "Disable scraping"

    def reset_error_count(self, request, queryset):
        queryset.update(error_count=0, last_error=None, scraping_status="idle")
        self.message_user(request, f"Reset error count for {queryset.count()} sources.")

    reset_error_count.short_description = "Reset error count"


class TradeInline(admin.TabularInline):
    model = Trade
    extra = 0
    readonly_fields = (
        "status",
        "entry_price",
        "exit_price",
        "current_pnl",
        "created_at",
    )
    fields = (
        "symbol",
        "direction",
        "quantity",
        "status",
        "entry_price",
        "exit_price",
        "current_pnl",
        "created_at",
    )

    def current_pnl(self, obj):
        pnl = obj.current_pnl
        if pnl is None:
            return "-"
        try:
            pnl = float(pnl)
            if pnl > 0:
                return format_html('<span style="color: green;">+${:.2f}</span>', pnl)
            elif pnl < 0:
                return format_html('<span style="color: red;">${:.2f}</span>', pnl)
            return f"${pnl:.2f}"
        except (ValueError, TypeError):
            return "-"

    current_pnl.short_description = "P&L"


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source_name",
        "content_preview",
        "has_analysis",
        "created_at",
    )
    list_filter = ("source", "created_at")
    search_fields = ("content", "url")
    readonly_fields = ("created_at", "api_response")
    date_hierarchy = "created_at"

    def source_name(self, obj):
        return obj.source.name

    source_name.short_description = "Source"

    def content_preview(self, obj):
        return obj.content[:100] + "..." if len(obj.content) > 100 else obj.content

    content_preview.short_description = "Content"

    def has_analysis(self, obj):
        try:
            analysis = obj.analysis
            if analysis.direction in ["buy", "sell"]:
                return format_html(
                    '<span style="color: green;">✓ {}</span>',
                    analysis.direction.upper(),
                )
            return format_html('<span style="color: orange;">✓ HOLD</span>')
        except Analysis.DoesNotExist:
            return format_html('<span style="color: red;">✗</span>')

    has_analysis.short_description = "Analysis"
    has_analysis.admin_order_field = "analysis"


@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "post_id",
        "symbol",
        "direction",
        "confidence",
        "has_trades",
        "created_at",
    )
    list_filter = ("direction", "symbol", "created_at")
    search_fields = ("symbol", "reason", "post__content")
    readonly_fields = ("post", "raw_llm_response", "created_at")
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Analysis Results",
            {"fields": ("post", "symbol", "direction", "confidence", "reason")},
        ),
        (
            "Enhanced Analysis",
            {
                "fields": (
                    "trading_config_used",
                    "sentiment_score",
                    "market_impact_score",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Raw Data",
            {
                "fields": ("raw_llm_response",),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [TradeInline]

    def post_id(self, obj):
        return obj.post.id

    post_id.short_description = "Post ID"

    def has_trades(self, obj):
        count = obj.trades.count()
        if count > 0:
            return format_html('<span style="color: green;">{} trades</span>', count)
        return format_html('<span style="color: gray;">No trades</span>')

    has_trades.short_description = "Trades"


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "symbol",
        "direction",
        "quantity",
        "status",
        "entry_price",
        "exit_price",
        "pnl_display",
        "duration",
        "created_at",
    )
    list_filter = ("status", "direction", "symbol", "close_reason", "created_at")
    search_fields = ("symbol", "alpaca_order_id")
    readonly_fields = (
        "analysis",
        "alpaca_order_id",
        "created_at",
        "updated_at",
        "duration_display",
        "pnl_display",
    )
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Trade Details",
            {"fields": ("analysis", "symbol", "direction", "quantity", "status")},
        ),
        (
            "Pricing",
            {
                "fields": (
                    "entry_price",
                    "exit_price",
                    "stop_loss_price",
                    "take_profit_price",
                )
            },
        ),
        (
            "P&L Tracking",
            {
                "fields": (
                    "unrealized_pnl",
                    "realized_pnl",
                    "commission",
                    "pnl_display",
                ),
            },
        ),
        (
            "External Systems",
            {
                "fields": ("alpaca_order_id",),
                "classes": ("collapse",),
            },
        ),
        (
            "Closure Information",
            {
                "fields": ("close_reason", "closed_at"),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at", "opened_at", "duration_display"),
                "classes": ("collapse",),
            },
        ),
    )

    actions = ["close_trades_manually", "cancel_pending_trades"]

    def pnl_display(self, obj):
        pnl = obj.current_pnl
        if pnl is None:
            return "-"
        try:
            pnl = float(pnl)
            if pnl > 0:
                return format_html(
                    '<span style="color: green; font-weight: bold;">+${:.2f}</span>', pnl
                )
            elif pnl < 0:
                return format_html(
                    '<span style="color: red; font-weight: bold;">${:.2f}</span>', pnl
                )
            return f"${pnl:.2f}"
        except (ValueError, TypeError):
            return "-"

    pnl_display.short_description = "P&L"

    def duration(self, obj):
        duration = obj.duration_minutes
        if duration:
            hours = duration // 60
            minutes = duration % 60
            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        return "-"

    duration.short_description = "Duration"

    def duration_display(self, obj):
        return self.duration(obj)

    duration_display.short_description = "Trade Duration"

    def close_trades_manually(self, request, queryset):
        from .tasks import close_trade_manually

        count = 0
        for trade in queryset.filter(status="open"):
            close_trade_manually.delay(trade.id)
            count += 1
        self.message_user(request, f"Initiated manual close for {count} trades.")

    close_trades_manually.short_description = "Close selected trades manually"

    def cancel_pending_trades(self, request, queryset):
        updated = queryset.filter(status="pending").update(status="cancelled")
        self.message_user(request, f"Cancelled {updated} pending trades.")

    cancel_pending_trades.short_description = "Cancel pending trades"


@admin.register(ApiResponse)
class ApiResponseAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "url", "posts_count", "created_at")
    list_filter = ("source", "created_at")
    search_fields = ("url", "source__name")
    readonly_fields = ("raw_content", "created_at")
    date_hierarchy = "created_at"

    inlines = [PostInline]

    def posts_count(self, obj):
        return obj.posts.count()

    posts_count.short_description = "Posts"


# Customize admin site
admin.site.site_header = "News Trader Administration"
admin.site.site_title = "News Trader Admin"
admin.site.index_title = "Welcome to News Trader Administration"
