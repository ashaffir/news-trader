from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .api import (
    SourceViewSet,
    PostViewSet,
    AnalysisViewSet,
    TradeViewSet,
    ApiResponseViewSet,
    TradingConfigViewSet,
)

# API Router
router = DefaultRouter()
router.register(r"sources", SourceViewSet)
router.register(r"posts", PostViewSet)
router.register(r"analyses", AnalysisViewSet)
router.register(r"trades", TradeViewSet)
router.register(r"api-responses", ApiResponseViewSet)
router.register(r"trading-configs", TradingConfigViewSet)

urlpatterns = [
    # Web interface URLs
    path("", views.dashboard_view, name="dashboard"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("test-page/", views.test_page_view, name="test_page"),
    path("close-trade/", views.manual_close_trade_view, name="manual_close_trade"),
    # System status API
    path("api/system-status/", views.system_status_api, name="system_status_api"),
    path(
        "api/check-connection/<str:service>/",
        views.check_single_connection,
        name="check_single_connection",
    ),
    # API URLs
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
    path("api/toggle-bot-status/", views.toggle_bot_status, name="toggle_bot_status"),
]
