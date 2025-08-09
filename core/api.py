from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q, Count, Avg, Sum
from .models import Source, Post, Analysis, Trade, TradingConfig, ApiResponse
from .tasks import scrape_posts, analyze_post, execute_trade, close_trade_manually


# Serializers
class TradingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradingConfig
        fields = "__all__"


class SourceSerializer(serializers.ModelSerializer):
    posts_count = serializers.SerializerMethodField()

    class Meta:
        model = Source
        fields = "__all__"

    def get_posts_count(self, obj):
        return obj.individual_posts.count()


class PostSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    has_analysis = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = "__all__"

    def get_has_analysis(self, obj):
        try:
            return {
                "exists": True,
                "symbol": obj.analysis.symbol,
                "direction": obj.analysis.direction,
                "confidence": obj.analysis.confidence,
            }
        except Analysis.DoesNotExist:
            return {"exists": False}


class AnalysisSerializer(serializers.ModelSerializer):
    post_content_preview = serializers.SerializerMethodField()
    trades_count = serializers.SerializerMethodField()

    class Meta:
        model = Analysis
        fields = "__all__"

    def get_post_content_preview(self, obj):
        content = obj.post.content
        return content[:100] + "..." if len(content) > 100 else content

    def get_trades_count(self, obj):
        return obj.trades.count()


class TradeSerializer(serializers.ModelSerializer):
    current_pnl = serializers.ReadOnlyField()
    duration_minutes = serializers.ReadOnlyField()
    analysis_symbol = serializers.CharField(source="analysis.symbol", read_only=True)
    analysis_confidence = serializers.FloatField(
        source="analysis.confidence", read_only=True
    )

    class Meta:
        model = Trade
        fields = "__all__"


class ApiResponseSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    posts_count = serializers.SerializerMethodField()

    class Meta:
        model = ApiResponse
        fields = "__all__"

    def get_posts_count(self, obj):
        return obj.posts.count()


# ViewSets
class TradingConfigViewSet(viewsets.ModelViewSet):
    queryset = TradingConfig.objects.all()
    serializer_class = TradingConfigSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Activate a trading configuration and deactivate others."""
        config = self.get_object()
        TradingConfig.objects.update(is_active=False)
        config.is_active = True
        config.save()
        return Response({"status": "Configuration activated"})

    @action(detail=False, methods=["get"])
    def active(self, request):
        """Get the currently active trading configuration."""
        config = TradingConfig.objects.filter(is_active=True).first()
        if not config:
            return Response({"detail": "No active configuration"}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(config).data)


class SourceViewSet(viewsets.ModelViewSet):
    queryset = Source.objects.all()
    serializer_class = SourceSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def trigger_scrape(self, request, pk=None):
        """Manually trigger scraping for a specific source."""
        source = self.get_object()
        scrape_posts.delay(source_id=source.id)
        return Response({"status": "Scraping triggered", "source": source.name})

    @action(detail=False, methods=["post"])
    def trigger_all_scrape(self, request):
        """Manually trigger scraping for all enabled sources."""
        scrape_posts.delay()
        return Response({"status": "Scraping triggered for all sources"})

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        """Enable scraping for a source."""
        source = self.get_object()
        source.scraping_enabled = True
        source.scraping_status = "idle"
        source.save()
        return Response({"status": "Source enabled"})

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        """Disable scraping for a source."""
        source = self.get_object()
        source.scraping_enabled = False
        source.scraping_status = "disabled"
        source.save()
        return Response({"status": "Source disabled"})


class PostViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Post.objects.all().order_by("-created_at")
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def trigger_analysis(self, request, pk=None):
        """Manually trigger analysis for a specific post."""
        post = self.get_object()
        if hasattr(post, "analysis"):
            return Response(
                {"error": "Post already has analysis"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        analyze_post.delay(post.id)
        return Response({"status": "Analysis triggered", "post_id": post.id})

    def get_queryset(self):
        queryset = super().get_queryset()
        source_id = self.request.query_params.get("source_id")
        has_analysis = self.request.query_params.get("has_analysis")

        if source_id:
            queryset = queryset.filter(source_id=source_id)
        if has_analysis is not None:
            has_analysis_bool = has_analysis.lower() == "true"
            if has_analysis_bool:
                queryset = queryset.filter(analysis__isnull=False)
            else:
                queryset = queryset.filter(analysis__isnull=True)

        return queryset


class AnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Analysis.objects.all().order_by("-created_at")
    serializer_class = AnalysisSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def trigger_trade(self, request, pk=None):
        """Manually trigger trade execution for an analysis."""
        analysis = self.get_object()
        if analysis.direction == "hold":
            return Response(
                {"error": "Cannot execute trade for HOLD direction"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        execute_trade.delay(analysis.id)
        return Response(
            {"status": "Trade execution triggered", "analysis_id": analysis.id}
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        direction = self.request.query_params.get("direction")
        symbol = self.request.query_params.get("symbol")
        min_confidence = self.request.query_params.get("min_confidence")

        if direction:
            queryset = queryset.filter(direction=direction)
        if symbol:
            queryset = queryset.filter(symbol__icontains=symbol)
        if min_confidence:
            try:
                min_conf = float(min_confidence)
                queryset = queryset.filter(confidence__gte=min_conf)
            except ValueError:
                pass

        return queryset


class TradeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Trade.objects.all().order_by("-created_at")
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Manually close an open trade."""
        trade = self.get_object()
        if trade.status != "open":
            return Response(
                {"error": "Trade is not open"}, status=status.HTTP_400_BAD_REQUEST
            )
        close_trade_manually.delay(trade.id)
        return Response({"status": "Trade closure triggered", "trade_id": trade.id})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Get trading summary statistics."""
        trades = self.get_queryset()

        summary = {
            "total_trades": trades.count(),
            "open_trades": trades.filter(status__in=["open", "pending_close"]).count(),
            "closed_trades": trades.filter(status="closed").count(),
            "total_pnl": trades.filter(realized_pnl__isnull=False).aggregate(
                total=Sum("realized_pnl")
            )["total"]
            or 0,
            "avg_trade_duration": self._calculate_avg_duration(trades),
            "win_rate": self._calculate_win_rate(trades),
            "top_symbols": self._get_top_symbols(trades),
        }

        return Response(summary)

    def _calculate_win_rate(self, trades):
        """Calculate win rate for closed trades."""
        closed_trades = trades.filter(status="closed", realized_pnl__isnull=False)
        if not closed_trades.exists():
            return 0
        winning_trades = closed_trades.filter(realized_pnl__gt=0).count()
        return round((winning_trades / closed_trades.count()) * 100, 2)

    def _get_top_symbols(self, trades):
        """Get top 5 traded symbols."""
        return list(
            trades.values("symbol")
            .annotate(count=Count("symbol"), total_pnl=Sum("realized_pnl"))
            .order_by("-count")[:5]
        )

    def _calculate_avg_duration(self, trades):
        """Calculate average trade duration for closed trades."""
        closed_trades = trades.filter(
            status="closed", opened_at__isnull=False, closed_at__isnull=False
        )
        if not closed_trades.exists():
            return None

        total_duration = 0
        count = 0
        for trade in closed_trades:
            if trade.duration_minutes:
                total_duration += trade.duration_minutes
                count += 1

        return total_duration / count if count > 0 else None

    def get_queryset(self):
        queryset = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        symbol = self.request.query_params.get("symbol")
        direction = self.request.query_params.get("direction")

        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if symbol:
            queryset = queryset.filter(symbol__icontains=symbol)
        if direction:
            queryset = queryset.filter(direction=direction)

        return queryset


class ApiResponseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ApiResponse.objects.all().order_by("-created_at")
    serializer_class = ApiResponseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        source_id = self.request.query_params.get("source_id")

        if source_id:
            queryset = queryset.filter(source_id=source_id)

        return queryset
