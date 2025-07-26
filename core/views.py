from django.shortcuts import render, redirect
from .models import Trade, Post, Analysis, Source # Import Source model
from .tasks import close_trade_manually, scrape_posts, analyze_post, execute_trade
import logging
import json

logger = logging.getLogger(__name__)

def dashboard_view(request):
    logger.info("Dashboard view accessed.")
    return render(request, 'core/dashboard.html')

def manual_close_trade_view(request):
    logger.info("Manual close trade view accessed.")
    open_trades = Trade.objects.filter(status='open')

    if request.method == 'POST':
        trade_id = request.POST.get('trade_id')
        if trade_id:
            logger.info(f"Attempting to close trade with ID: {trade_id}")
            try:
                trade = Trade.objects.get(id=trade_id, status='open')
                close_trade_manually.delay(trade.id)
                logger.info(f"Initiated manual close for trade {trade.id}.")
                return redirect('manual_close_trade') # Redirect to refresh the page
            except Trade.DoesNotExist:
                logger.warning(f"Attempted to close non-existent or already closed trade with ID: {trade_id}")
                # Handle error: trade not found or not open
                pass
            except Exception as e:
                logger.error(f"An unexpected error occurred while processing manual close for trade {trade_id}: {e}")

    return render(request, 'core/manual_close_trade.html', {'open_trades': open_trades})

def test_page_view(request):
    logger.info("Test page accessed.")
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'trigger_scrape':
            source_id = request.POST.get('source_id')
            if source_id:
                try:
                    # Pass only the source_id to the scrape_posts task
                    scrape_posts.delay(source_id=source_id)
                    logger.info(f"Manually triggered scrape_posts task for Source ID: {source_id}.")
                except Source.DoesNotExist:
                    logger.warning(f"Source with ID {source_id} not found for scraping.")
            else:
                logger.warning("No Source ID provided for manual scrape trigger.")
        elif action == 'trigger_analysis':
            post_id = request.POST.get('post_id')
            if post_id:
                try:
                    post = Post.objects.get(id=post_id)
                    analyze_post.delay(post.id)
                    logger.info(f"Manually triggered analyze_post task for Post ID: {post_id}.")
                except Post.DoesNotExist:
                    logger.warning(f"Post with ID {post_id} not found for analysis.")
            else:
                logger.warning("No Post ID provided for manual analysis trigger.")
        elif action == 'trigger_trade':
            analysis_id = request.POST.get('analysis_id')
            if analysis_id:
                try:
                    analysis = Analysis.objects.get(id=analysis_id)
                    execute_trade.delay(analysis.id)
                    logger.info(f"Manually triggered execute_trade task for Analysis ID: {analysis_id}.")
                except Analysis.DoesNotExist:
                    logger.warning(f"Analysis with ID {analysis_id} not found for trade execution.")
            else:
                logger.warning("No Analysis ID provided for manual trade trigger.")

        return redirect('test_page') # Redirect to refresh the page and prevent form resubmission

    # Fetch some recent posts and analyses to display for manual triggering
    recent_posts = Post.objects.order_by('-created_at')[:10]
    recent_analyses = Analysis.objects.order_by('-created_at')[:10]
    sources = Source.objects.all() # Fetch all sources

    return render(request, 'core/test_page.html', {
        'recent_posts': recent_posts,
        'recent_analyses': recent_analyses,
        'sources': sources # Pass sources to the template
    })
