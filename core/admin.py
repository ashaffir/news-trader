from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Source, Post, Analysis, Trade, TradingConfig, ApiResponse, AlertSettings, TrackedCompany, ActivityLog
from django.utils import timezone
from datetime import timedelta
import json


@admin.register(TradingConfig)
class TradingConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "default_position_size",
        "max_concurrent_open_trades",
        "max_total_open_exposure",
        "stop_loss_percentage",
        "take_profit_percentage",
        "trailing_stop_enabled",
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
                    "trailing_stop_enabled",
                    "trailing_stop_distance_percentage",
                    "trailing_stop_activation_profit_percentage",
                    "min_confidence_threshold",
                ),
            },
        ),
        (
            "Position Management",
            {
                "fields": (
                    "max_position_hold_time_hours",
                    "min_confidence_for_adjustment",
                    "conservative_adjustment_factor",
                    "allow_position_adjustments",
                    "monitoring_frequency_minutes",
                ),
                "description": "Settings for enhanced position management and risk adjustment",
            },
        ),
        (
            "Trading Constraints",
            {
                "fields": ("max_daily_trades", "max_concurrent_open_trades", "max_total_open_exposure"),
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

    def posts_count(self, obj):
        try:
            return obj.individual_posts.count()
        except Exception:
            return 0
    posts_count.short_description = "Posts"
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


@admin.register(AlertSettings)
class AlertSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "enabled",
        "bot_status_enabled",
        "order_open_enabled",
        "order_close_enabled",
        "trading_limit_enabled",
        "updated_at",
    )
    list_filter = ("enabled",)
    readonly_fields = ("created_at", "updated_at")


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
        "stop_loss_price",
        "take_profit_price",
        "stop_loss_price_percentage",
        "take_profit_price_percentage",
        "created_at",
    )

    def current_pnl(self, obj):
        """Display P&L - realized P&L for closed trades, unrealized for open trades."""
        pnl = None
        
        if obj.status == "closed":
            # For closed trades, use realized_pnl from Alpaca
            pnl = obj.realized_pnl
        else:
            # For open trades, use unrealized_pnl
            pnl = obj.unrealized_pnl
        
        if pnl is None:
            return "-"
        
        try:
            pnl = float(pnl)
            if pnl > 0:
                return format_html('<span style="color: green;">+${}</span>', f'{pnl:.2f}')
            elif pnl < 0:
                return format_html('<span style="color: red;">${}</span>', f'{pnl:.2f}')
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
        "published_at",
        "has_analysis",
        "created_at",
    )
    list_filter = ("source", "published_at", "created_at")
    search_fields = ("content", "url")
    readonly_fields = ("created_at", "api_response")
    date_hierarchy = "published_at"

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
    # Keep filters/back-compat on symbol but add tracked_company for new FK
    list_filter = ("status", "direction", "symbol", "tracked_company", "close_reason", "created_at")
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
            {"fields": ("analysis", "tracked_company", "symbol", "direction", "quantity", "status")},
        ),
        (
            "Pricing",
            {
                "fields": (
                    "entry_price",
                    "exit_price",
                    "stop_loss_price",
                    "take_profit_price",
                    "stop_loss_price_percentage",
                    "take_profit_price_percentage",
                )
            },
        ),
        (
            "Position Adjustments",
            {
                "fields": (
                    "has_been_adjusted",
                    "original_stop_loss_price",
                    "original_take_profit_price",
                ),
                "classes": ("collapse",),
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
        """Display P&L - realized P&L for closed trades, unrealized for open trades."""
        pnl = None
        
        if obj.status == "closed":
            # For closed trades, use realized_pnl from Alpaca
            pnl = obj.realized_pnl
        else:
            # For open trades, use unrealized_pnl
            pnl = obj.unrealized_pnl
        
        if pnl is None:
            return "-"
        
        try:
            pnl = float(pnl)
            if pnl > 0:
                return format_html(
                    '<span style="color: green; font-weight: bold;">+${}</span>', f'{pnl:.2f}'
                )
            elif pnl < 0:
                return format_html(
                    '<span style="color: red; font-weight: bold;">${}</span>', f'{pnl:.2f}'
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


@admin.register(TrackedCompany)
class TrackedCompanyAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "sector", "industry", "market", "is_active", "updated_at")
    list_filter = ("is_active", "sector", "industry", "market")
    search_fields = ("symbol", "name", "sector", "industry")
    ordering = ("symbol",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Company", {"fields": ("symbol", "name", "sector", "industry", "market", "is_active")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


class RelatedObjectFilter(admin.SimpleListFilter):
    title = "Related object"
    parameter_name = "related"

    def lookups(self, request, model_admin):
        return (
            ("trade", "Trade"),
            ("post", "Post"),
            ("source", "Source"),
            ("analysis", "Analysis"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "trade":
            try:
                return queryset.filter(data__has_key="trade_id")
            except Exception:
                return queryset
        if value == "post":
            try:
                return queryset.filter(data__has_key="post_id")
            except Exception:
                return queryset
        if value == "source":
            try:
                return queryset.filter(data__has_key="source_id")
            except Exception:
                return queryset
        if value == "analysis":
            try:
                return queryset.filter(data__has_key="analysis_id")
            except Exception:
                return queryset
        return queryset


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "activity_badge",
        "message_short",
        "related_object_link",
    )
    list_filter = ("activity_type", RelatedObjectFilter, "created_at")
    search_fields = ("message",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    readonly_fields = ("created_at", "activity_type", "message", "data_pretty")
    fieldsets = (
        ("Activity", {"fields": ("activity_type", "message", "created_at")}),
        ("Details", {"fields": ("data_pretty",)}),
    )

    actions = [
        "prune_older_than_7_days",
        "prune_older_than_30_days",
        "prune_older_than_90_days",
    ]

    def activity_badge(self, obj):
        color = "#4a5568"  # gray
        atype = obj.activity_type or ""
        if "error" in atype or "rejected" in atype:
            color = "#e53e3e"  # red
        elif atype.startswith("trade"):
            color = "#3182ce"  # blue
        elif atype.startswith("analysis"):
            color = "#805ad5"  # purple
        elif atype.startswith("scraper"):
            color = "#2f855a"  # green
        return format_html(
            '<span style="background:{}; color:white; padding:2px 8px; border-radius:12px; font-size:12px;">{}</span>',
            color,
            atype.replace("_", " ").title(),
        )

    activity_badge.short_description = "Type"

    def message_short(self, obj):
        text = obj.message or ""
        return (text[:120] + "…") if len(text) > 120 else text

    message_short.short_description = "Message"

    def data_pretty(self, obj):
        try:
            pretty = json.dumps(obj.data or {}, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(obj.data)
        return mark_safe(f"<pre style=\"white-space:pre-wrap; word-break:break-word;\">{pretty}</pre>")

    data_pretty.short_description = "Data (JSON)"

    def related_object_link(self, obj):
        data = obj.data or {}
        # Priority: trade -> analysis -> post -> source
        if isinstance(data, dict):
            trade_id = data.get("trade_id")
            if trade_id:
                try:
                    url = reverse("admin:core_trade_change", args=[trade_id])
                    return format_html('<a href="{}">Trade #{}</a>', url, trade_id)
                except Exception:
                    pass
            analysis_id = data.get("analysis_id")
            if analysis_id:
                try:
                    url = reverse("admin:core_analysis_change", args=[analysis_id])
                    return format_html('<a href="{}">Analysis #{}</a>', url, analysis_id)
                except Exception:
                    pass
            post_id = data.get("post_id")
            if post_id:
                try:
                    url = reverse("admin:core_post_change", args=[post_id])
                    return format_html('<a href="{}">Post #{}</a>', url, post_id)
                except Exception:
                    pass
            source_id = data.get("source_id")
            if source_id:
                try:
                    url = reverse("admin:core_source_change", args=[source_id])
                    return format_html('<a href="{}">Source #{}</a>', url, source_id)
                except Exception:
                    pass
        return mark_safe("<span style=\"color:#718096;\">—</span>")

    related_object_link.short_description = "Related"

    def _prune_before(self, request, days):
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = ActivityLog.objects.filter(created_at__lt=cutoff).delete()
        self.message_user(request, f"Pruned {deleted} log entries older than {days} days.")

    def prune_older_than_7_days(self, request, queryset):
        self._prune_before(request, 7)

    prune_older_than_7_days.short_description = "Prune logs older than 7 days"

    def prune_older_than_30_days(self, request, queryset):
        self._prune_before(request, 30)

    prune_older_than_30_days.short_description = "Prune logs older than 30 days"

    def prune_older_than_90_days(self, request, queryset):
        self._prune_before(request, 90)

    prune_older_than_90_days.short_description = "Prune logs older than 90 days"
