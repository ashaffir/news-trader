from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Post, ApiResponse, ActivityLog
from core.utils.config import get_config_value


class Command(BaseCommand):
    help = "Clean up old data from the database (posts, API responses)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            help='Number of days to retain posts (overrides config)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        try:
            # Get retention period from command line or config
            if options['days']:
                retention_days = options['days']
                self.stdout.write(f"Using command line retention period: {retention_days} days")
            else:
                retention_days = get_config_value("posts_retention_days", 30)
                try:
                    retention_days = int(retention_days)
                except (ValueError, TypeError):
                    retention_days = 30
                self.stdout.write(f"Using configured retention period: {retention_days} days")

            # Calculate cutoff date
            cutoff_date = timezone.now() - timedelta(days=retention_days)
            self.stdout.write(f"Cleaning up data older than: {cutoff_date}")

            # Find old posts BUT exclude those that have trades (to preserve financial records)
            # We'll only delete posts that have no analysis, or analysis with no trades
            from core.models import Analysis, Trade
            
            # First get all posts older than cutoff
            all_old_posts = Post.objects.filter(created_at__lt=cutoff_date)
            
            # Exclude posts that have analyses with trades (preserve financial data)
            posts_with_trades = all_old_posts.filter(
                analysis__trades__isnull=False
            ).distinct()
            
            # Posts safe to delete: old posts that either have no analysis or analysis with no trades
            old_posts = all_old_posts.exclude(
                id__in=posts_with_trades.values_list('id', flat=True)
            )
            
            posts_count = old_posts.count()
            posts_with_trades_count = posts_with_trades.count()

            # Find orphaned API responses (those with no posts after cleanup)
            # We'll check this after posts are deleted
            
            if options['dry_run']:
                self.stdout.write(
                    self.style.WARNING(f"DRY RUN: Would delete {posts_count} posts older than {retention_days} days")
                )
                if posts_with_trades_count > 0:
                    self.stdout.write(
                        self.style.SUCCESS(f"PRESERVED: {posts_with_trades_count} posts with associated trades will be kept")
                    )
                
                # Sample some posts to show what would be deleted
                if posts_count > 0:
                    sample_posts = old_posts[:5]
                    self.stdout.write("Sample posts that would be deleted (no trades):")
                    for post in sample_posts:
                        self.stdout.write(f"  - Post {post.id}: {post.source.name} - {post.created_at}")
                    if posts_count > 5:
                        self.stdout.write(f"  ... and {posts_count - 5} more")
                else:
                    self.stdout.write("No posts found that can be safely deleted")
                
                return

            # Delete old posts (only those without trades)
            if posts_count > 0:
                self.stdout.write(f"Deleting {posts_count} old posts (preserving {posts_with_trades_count} posts with trades)...")
                deleted_posts = old_posts.delete()
            else:
                self.stdout.write("No posts found that can be safely deleted")
                deleted_posts = (0, {})
            
            # Clean up orphaned API responses (those with no posts)
            orphaned_responses = ApiResponse.objects.filter(posts__isnull=True)
            orphaned_count = orphaned_responses.count()
            
            if orphaned_count > 0:
                self.stdout.write(f"Deleting {orphaned_count} orphaned API responses...")
                deleted_responses = orphaned_responses.delete()
            else:
                deleted_responses = (0, {})

            # Log the cleanup activity
            ActivityLog.objects.create(
                activity_type="system_event",
                message="Old data cleanup completed",
                data={
                    "retention_days": retention_days,
                    "cutoff_date": cutoff_date.isoformat(),
                    "deleted_posts": deleted_posts[0] if deleted_posts else 0,
                    "preserved_posts_with_trades": posts_with_trades_count,
                    "deleted_api_responses": deleted_responses[0] if deleted_responses else 0,
                },
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully cleaned up old data:\n"
                    f"  - Deleted {deleted_posts[0] if deleted_posts else 0} posts\n"
                    f"  - Preserved {posts_with_trades_count} posts with associated trades\n"
                    f"  - Deleted {deleted_responses[0] if deleted_responses else 0} orphaned API responses\n"
                    f"  - Retention period: {retention_days} days"
                )
            )

        except Exception as e:
            error_msg = f"Old data cleanup failed: {str(e)}"
            self.stdout.write(self.style.ERROR(error_msg))
            
            # Log the error
            try:
                ActivityLog.objects.create(
                    activity_type="system_event",
                    message="Old data cleanup failed",
                    data={
                        "error": str(e),
                        "retention_days": retention_days if 'retention_days' in locals() else 'unknown',
                    "preserved_posts_with_trades": posts_with_trades_count if 'posts_with_trades_count' in locals() else 0,
                    },
                )
            except Exception:
                # Don't fail if we can't log the error
                pass
            
            raise e
