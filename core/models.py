from django.db import models

class Source(models.Model):
    """A source for scraping posts, e.g., a Twitter account or subreddit."""
    name = models.CharField(max_length=255)
    url = models.URLField(unique=True)
    description = models.TextField(blank=True, null=True)

    SCRAPING_METHOD_CHOICES = [
        ('web', 'Web Scraping'),
        ('api', 'API'),
        ('both', 'Web Scraping and API'),
    ]
    scraping_method = models.CharField(
        max_length=10,
        choices=SCRAPING_METHOD_CHOICES,
        default='web'
    )
    api_endpoint = models.URLField(blank=True, null=True)
    api_key_field = models.CharField(max_length=255, blank=True, null=True)

    REQUEST_TYPE_CHOICES = [
        ('GET', 'GET'),
        ('POST', 'POST'),
    ]
    request_type = models.CharField(
        max_length=10,
        choices=REQUEST_TYPE_CHOICES,
        default='GET'
    )
    request_params = models.JSONField(blank=True, null=True)

    def __str__(self):
        return self.name

class ApiResponse(models.Model):
    """A raw API response containing one or more posts."""
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='api_responses')
    raw_content = models.JSONField()
    url = models.URLField(unique=True) # URL of the API endpoint that was called
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_apiresponse' # Explicitly set table name for migration

    def __str__(self):
        return f"API Response from {self.source.name} at {self.created_at}"

class Post(models.Model):
    """An individual post extracted from an API response or scraped from the web."""
    api_response = models.ForeignKey(ApiResponse, on_delete=models.CASCADE, related_name='posts', null=True, blank=True)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='individual_posts')
    content = models.TextField()
    url = models.URLField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Post from {self.source.name} at {self.created_at}"

class Analysis(models.Model):
    """LLM analysis of a post."""
    DIRECTION_CHOICES = [
        ('buy', 'Buy'),
        ('sell', 'Sell'),
        ('hold', 'Hold'),
    ]

    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name='analysis')
    symbol = models.CharField(max_length=10)
    direction = models.CharField(max_length=4, choices=DIRECTION_CHOICES)
    confidence = models.FloatField()
    reason = models.TextField()
    raw_llm_response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Analysis for {self.post.id}: {self.symbol} {self.direction}"

class Trade(models.Model):
    """A trade executed based on an analysis."""
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]

    analysis = models.ForeignKey(Analysis, on_delete=models.CASCADE, related_name='trades')
    symbol = models.CharField(max_length=10)
    direction = models.CharField(max_length=4, choices=Analysis.DIRECTION_CHOICES)
    quantity = models.FloatField()
    entry_price = models.FloatField()
    exit_price = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Trade {self.id}: {self.direction} {self.quantity} {self.symbol} @ {self.entry_price}"