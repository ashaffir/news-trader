import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

import core.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "news_trader.settings")

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        # Just for websocket for now
        "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(
            URLRouter(
                core.routing.websocket_urlpatterns
            )
        )),
    }
)