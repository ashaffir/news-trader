from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class TradingConfig(models.Model):
    """Global trading configuration and risk management parameters."""

    name = models.CharField(max_length=255, default="Default Config")

    # Position sizing
    default_position_size = models.FloatField(
        default=100.0, help_text="Default position size in dollars"
    )
    max_position_size = models.FloatField(
        default=1000.0, help_text="Maximum position size in dollars"
    )
    position_sizing_method = models.CharField(
        max_length=20,
        choices=[
            ("fixed", "Fixed Amount"),
            ("percentage", "Percentage of Portfolio"),
            ("risk_based", "Risk-Based Sizing"),
        ],
        default="fixed",
    )

    # Risk management
    stop_loss_percentage = models.FloatField(
        default=2.0,
        validators=[MinValueValidator(0.1), MaxValueValidator(50.0)],
        help_text="Stop loss percentage (1.0 = 1%)",
    )
    take_profit_percentage = models.FloatField(
        default=10.0,
        validators=[MinValueValidator(0.1), MaxValueValidator(100.0)],
        help_text="Take profit percentage (1.0 = 1%)",
    )

    # Trading constraints
    max_daily_trades = models.IntegerField(
        default=10, help_text="Maximum trades per day"
    )
    max_concurrent_open_trades = models.IntegerField(
        default=5,
        validators=[MinValueValidator(0)],
        help_text="Maximum number of trades that can be open (including pending/pending close) at the same time",
    )
    max_total_open_exposure = models.FloatField(
        default=5000.0,
        validators=[MinValueValidator(0.0)],
        help_text="Maximum total dollar exposure across all open positions",
    )
    min_confidence_threshold = models.FloatField(
        default=0.7,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Minimum LLM confidence to execute trade",
    )

    # Position management
    max_position_hold_time_hours = models.IntegerField(
        default=24, 
        validators=[MinValueValidator(1), MaxValueValidator(168)],  # 1 hour to 1 week
        help_text="Maximum hours to hold a position before automatic close"
    )
    min_confidence_for_adjustment = models.FloatField(
        default=0.8,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Minimum confidence required to adjust existing position TP/SL"
    )
    conservative_adjustment_factor = models.FloatField(
        default=0.5,
        validators=[MinValueValidator(0.1), MaxValueValidator(1.0)],
        help_text="Conservative factor for TP/SL adjustments (0.5 = 50% of full adjustment)"
    )
    allow_position_adjustments = models.BooleanField(
        default=True,
        help_text="Allow one-time TP/SL adjustments based on new supporting analysis"
    )
    monitoring_frequency_minutes = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="How often to monitor positions for TP/SL triggers (in minutes)"
    )

    # LLM Configuration
    llm_model = models.CharField(max_length=100, default="gpt-3.5-turbo")
    llm_prompt_template = models.TextField(
        default="""You are a financial analyst. Analyze the given text for potential financial impact on a stock. 
Respond with a JSON object: { "symbol": "STOCK_SYMBOL", "direction": "buy", "confidence": 0.87, "reason": "Explanation" }. 
Direction can be 'buy', 'sell', or 'hold'. Confidence is a float between 0 and 1.""",
        help_text="LLM prompt template for financial analysis",
    )

    # Trading hours
    trading_enabled = models.BooleanField(default=True)
    market_hours_only = models.BooleanField(
        default=True, help_text="Only trade during market hours"
    )

    # Bot control
    bot_enabled = models.BooleanField(
        default=False,
        help_text="Master switch to enable/disable all bot activities (scraping, analysis, trading)",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "-created_at"]

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"


class Source(models.Model):
    """A source for scraping posts, e.g., a Twitter account or subreddit."""

    name = models.CharField(max_length=255)
    url = models.URLField(unique=True)
    description = models.TextField(blank=True, null=True)

    # Data extraction configuration
    data_extraction_config = models.JSONField(
        blank=True,
        null=True,
        help_text="JSON config for data extraction rules (CSS selectors, JSON paths, etc.)",
    )

    SCRAPING_METHOD_CHOICES = [
        ("web", "Web Scraping"),
        ("api", "API"),
        ("both", "Web Scraping and API"),
    ]
    scraping_method = models.CharField(
        max_length=10, choices=SCRAPING_METHOD_CHOICES, default="web"
    )
    api_endpoint = models.URLField(blank=True, null=True)
    api_key_field = models.CharField(max_length=255, blank=True, null=True)

    REQUEST_TYPE_CHOICES = [
        ("GET", "GET"),
        ("POST", "POST"),
    ]
    request_type = models.CharField(
        max_length=10, choices=REQUEST_TYPE_CHOICES, default="GET"
    )
    request_params = models.JSONField(blank=True, null=True)

    # Scheduling and status
    scraping_enabled = models.BooleanField(default=True)
    scraping_interval_minutes = models.IntegerField(
        default=5, help_text="Scraping interval in minutes"
    )
    last_scraped_at = models.DateTimeField(blank=True, null=True)
    scraping_status = models.CharField(
        max_length=20,
        choices=[
            ("idle", "Idle"),
            ("running", "Running"),
            ("error", "Error"),
            ("disabled", "Disabled"),
        ],
        default="idle",
    )
    error_count = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ApiResponse(models.Model):
    """A raw API response containing one or more posts."""

    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="api_responses"
    )
    raw_content = models.JSONField()
    url = models.URLField(unique=True)  # URL of the API endpoint that was called
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_apiresponse"  # Explicitly set table name for migration

    def __str__(self):
        return f"API Response from {self.source.name} at {self.created_at}"


class Post(models.Model):
    """An individual post extracted from an API response or scraped from the web."""

    api_response = models.ForeignKey(
        ApiResponse,
        on_delete=models.CASCADE,
        related_name="posts",
        null=True,
        blank=True,
    )
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="individual_posts"
    )
    content = models.TextField()
    url = models.URLField(unique=True, max_length=600)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Post from {self.source.name} at {self.created_at}"


class Analysis(models.Model):
    """LLM analysis of a post."""

    DIRECTION_CHOICES = [
        ("buy", "Buy"),
        ("sell", "Sell"),
        ("hold", "Hold"),
    ]

    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name="analysis")
    symbol = models.CharField(max_length=10)
    direction = models.CharField(max_length=4, choices=DIRECTION_CHOICES)
    confidence = models.FloatField()
    reason = models.TextField()
    raw_llm_response = models.JSONField(null=True, blank=True)

    # Enhanced analysis fields
    trading_config_used = models.ForeignKey(
        TradingConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Trading config used for this analysis",
    )
    sentiment_score = models.FloatField(
        null=True, blank=True, help_text="Sentiment score from -1 to 1"
    )
    market_impact_score = models.FloatField(
        null=True, blank=True, help_text="Predicted market impact score"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Analysis for {self.post.id}: {self.symbol} {self.direction}"


class Trade(models.Model):
    """A trade executed based on an analysis."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("open", "Open"),
        ("pending_close", "Open - Pending Close"),
        ("closed", "Closed"),
        ("cancelled", "Cancelled"),
        ("failed", "Failed"),
    ]

    CLOSE_REASON_CHOICES = [
        ("manual", "Manual Close"),
        ("stop_loss", "Stop Loss"),
        ("take_profit", "Take Profit"),
        ("time_limit", "Time Limit"),
        ("market_close", "Market Close"),
        ("market_consensus_lost", "Market Consensus Lost"),
    ]

    analysis = models.ForeignKey(
        Analysis, on_delete=models.CASCADE, related_name="trades", null=True, blank=True
    )
    symbol = models.CharField(max_length=10)
    direction = models.CharField(max_length=4, choices=Analysis.DIRECTION_CHOICES)
    quantity = models.FloatField()
    entry_price = models.FloatField()
    exit_price = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="pending")

    # Enhanced trade tracking
    alpaca_order_id = models.CharField(max_length=100, blank=True, null=True)
    stop_loss_price = models.FloatField(null=True, blank=True)
    take_profit_price = models.FloatField(null=True, blank=True)
    stop_loss_price_percentage = models.FloatField(null=True, blank=True)
    take_profit_price_percentage = models.FloatField(null=True, blank=True)
    close_reason = models.CharField(
        max_length=25, choices=CLOSE_REASON_CHOICES, blank=True, null=True
    )

    # Position adjustment tracking
    has_been_adjusted = models.BooleanField(
        default=False, 
        help_text="Whether TP/SL has been adjusted (one-time only)"
    )
    original_stop_loss_price = models.FloatField(
        null=True, blank=True,
        help_text="Original stop loss price before any adjustments"
    )
    original_take_profit_price = models.FloatField(
        null=True, blank=True,
        help_text="Original take profit price before any adjustments"
    )

    # P&L tracking
    unrealized_pnl = models.FloatField(default=0.0)
    realized_pnl = models.FloatField(null=True, blank=True)
    commission = models.FloatField(default=0.0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['symbol'],
                condition=models.Q(status__in=['open', 'pending', 'pending_close']),
                name='unique_active_trade_per_symbol'
            )
        ]

    def __str__(self):
        entry_price = self.entry_price if self.entry_price is not None else "N/A"
        return f"Trade {self.id}: {self.direction} {self.quantity} {self.symbol} @ {entry_price}"

    @property
    def duration_minutes(self):
        """Calculate trade duration in minutes."""
        if self.opened_at and self.closed_at:
            return int((self.closed_at - self.opened_at).total_seconds() / 60)
        return None

    @property
    def current_pnl(self):
        """Get current P&L (realized if closed, unrealized if open)."""
        if self.status == "closed" and self.realized_pnl is not None:
            return self.realized_pnl
        return self.unrealized_pnl or 0.0

    def save(self, *args, **kwargs):
        """Ensure default TP/SL percentages and prices are set on creation.

        Defaults: take profit 10%, stop loss 2%.
        Prices are computed only when an entry price is available and the
        corresponding price field is not already set.
        """
        is_new = self.pk is None

        # Apply default percentages on create if missing
        if is_new:
            if self.take_profit_price_percentage is None:
                self.take_profit_price_percentage = 10.0
            if self.stop_loss_price_percentage is None:
                self.stop_loss_price_percentage = 2.0

        # Compute price levels from percentages if we have an entry price
        try:
            has_entry = self.entry_price is not None and float(self.entry_price) > 0
            if has_entry and self.direction in ("buy", "sell"):
                tp_pct = self.take_profit_price_percentage
                sl_pct = self.stop_loss_price_percentage
                if tp_pct is not None and self.take_profit_price in (None, 0):
                    if self.direction == "buy":
                        self.take_profit_price = float(self.entry_price) * (1 + float(tp_pct) / 100.0)
                    else:
                        self.take_profit_price = float(self.entry_price) * (1 - float(tp_pct) / 100.0)
                if sl_pct is not None and self.stop_loss_price in (None, 0):
                    if self.direction == "buy":
                        self.stop_loss_price = float(self.entry_price) * (1 - float(sl_pct) / 100.0)
                    else:
                        self.stop_loss_price = float(self.entry_price) * (1 + float(sl_pct) / 100.0)

                # Initialize original levels if not set
                if self.original_take_profit_price is None and self.take_profit_price is not None:
                    self.original_take_profit_price = self.take_profit_price
                if self.original_stop_loss_price is None and self.stop_loss_price is not None:
                    self.original_stop_loss_price = self.stop_loss_price
        except Exception:
            # Do not block save on computation errors
            pass

        super().save(*args, **kwargs)


class ActivityLog(models.Model):
    """Database-based activity log for dashboard activities."""
    ACTIVITY_TYPES = [
        ('new_post', 'New Post'),
        ('analysis_complete', 'Analysis Complete'),
        ('trade_executed', 'Trade Executed'),
        ('trade_closed', 'Trade Closed'),
        ('trade_close_requested', 'Trade Close Requested'),
        ('scraper_error', 'Scraper Error'),
        ('scraper_status', 'Scraper Status'),
        ('scraper_skipped', 'Scraper Skipped'),
        ('trade_status', 'Trade Status'),
        ('trade_rejected', 'Trade Rejected'),
        ('system_event', 'System Event'),
    ]
    
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['activity_type']),
        ]
    
    def __str__(self):
        return f"{self.activity_type}: {self.message[:100]}"


class AlertSettings(models.Model):
    """User-configurable alert preferences for outbound notifications."""

    enabled = models.BooleanField(
        default=True, help_text="Master enable/disable for all outbound alerts"
    )

    # Individual alert toggles
    bot_status_enabled = models.BooleanField(
        default=True, help_text="Send alert when bot is enabled/disabled"
    )
    order_open_enabled = models.BooleanField(
        default=True, help_text="Send alert when an order is opened (filled)"
    )
    order_close_enabled = models.BooleanField(
        default=True, help_text="Send alert when an order is closed"
    )
    trading_limit_enabled = models.BooleanField(
        default=True, help_text="Send alert when a trading limit is reached"
    )

    # Periodic heartbeat when bot is enabled
    heartbeat_enabled = models.BooleanField(
        default=False, help_text="Send periodic bot heartbeat while bot is enabled"
    )
    heartbeat_interval_minutes = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
        help_text="Heartbeat interval in minutes (default 30)"
    )
    last_heartbeat_sent = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last heartbeat alert sent"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"AlertSettings (enabled={self.enabled})"


class TwitterSession(models.Model):
    """Stored login state for a Twitter/X account to enable authenticated scraping.

    Stores storage_state and cookies captured from Playwright after a successful login
    flow. Credentials are stored for convenience in development only; consider
    encrypting or removing in production.
    """

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True)

    # Playwright storage state JSON (contains cookies/localStorage) for re-use
    storage_state = models.JSONField(blank=True, null=True)
    cookies = models.JSONField(blank=True, null=True)

    last_login_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("ok", "OK"),
            ("pending", "Pending"),
            ("error", "Error"),
        ],
        default="ok",
    )
    last_error = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"TwitterSession({self.username})"
