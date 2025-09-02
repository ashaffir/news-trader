from django.core.management.base import BaseCommand
from core.models import TwitterSession, Source
from django.utils import timezone


class Command(BaseCommand):
    help = "Check Twitter scraping setup and provide guidance"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("🐦 Checking Twitter scraping setup...")
        )

        # Check for Twitter sources
        twitter_sources = Source.objects.filter(
            url__icontains='x.com'
        ) | Source.objects.filter(
            url__icontains='twitter.com'
        )
        
        self.stdout.write(f"\n📊 Found {twitter_sources.count()} Twitter sources:")
        for source in twitter_sources:
            enabled_status = "✅ Enabled" if source.scraping_enabled else "❌ Disabled"
            self.stdout.write(f"  - {source.name}: {source.url} ({enabled_status})")

        # Check for Twitter sessions
        try:
            sessions = TwitterSession.objects.all()
            self.stdout.write(f"\n🔐 Found {sessions.count()} Twitter sessions:")
            
            if sessions.exists():
                for session in sessions:
                    age = timezone.now() - session.updated_at
                    age_hours = age.total_seconds() / 3600
                    
                    if age_hours < 24:
                        status = "🟢 Fresh"
                    elif age_hours < 48:
                        status = "🟡 Aging"
                    else:
                        status = "🔴 Stale"
                        
                    self.stdout.write(f"  - @{session.username}: {status} ({age_hours:.1f}h old)")
            else:
                self.stdout.write("  ❌ No Twitter sessions found!")
        except Exception as e:
            self.stdout.write(f"\n🔐 Error checking Twitter sessions: {e}")
            self.stdout.write("  (This may be normal if TwitterSession table doesn't exist yet)")

        # Provide guidance
        self.stdout.write("\n💡 Recommendations:")
        
        # Check if we have sessions (handle the case where sessions might not be accessible)
        has_sessions = False
        try:
            has_sessions = sessions.exists()
        except:
            has_sessions = False
        
        if not has_sessions and twitter_sources.exists():
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  You have Twitter sources but no authentication sessions!"
                )
            )
            self.stdout.write("   Twitter sources will fail to scrape without authentication.")
            self.stdout.write("\n   To fix this:")
            self.stdout.write("   1. Run: python manage.py create_twitter_session")
            self.stdout.write("   2. Or manually create a TwitterSession via Django admin")
            self.stdout.write("   3. Or disable Twitter sources if not needed")
            
        elif has_sessions:
            try:
                fresh_sessions = [s for s in sessions if (timezone.now() - s.updated_at).total_seconds() < 86400]
                if fresh_sessions:
                    self.stdout.write("✅ Twitter scraping should work properly")
                else:
                    self.stdout.write("⚠️  All Twitter sessions are stale - consider refreshing")
            except:
                self.stdout.write("⚠️  Could not check session freshness")
                
        if not twitter_sources.exists():
            self.stdout.write("ℹ️  No Twitter sources configured")
