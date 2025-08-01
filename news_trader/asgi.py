import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "news_trader.local_settings")

# Simple ASGI application - no WebSockets needed, using polling instead
application = get_asgi_application()