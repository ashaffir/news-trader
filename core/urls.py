from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('close-trade/', views.manual_close_trade_view, name='manual_close_trade'),
    path('test-page/', views.test_page_view, name='test_page'),
]
