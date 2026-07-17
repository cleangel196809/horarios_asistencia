"""SIIHAPI · ASGI entrypoint (WebSockets via Channels)."""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siihapi.settings')
django_asgi_app = get_asgi_application()

# Importar después de configurar Django
from apps.horarios.routing import websocket_urlpatterns as horarios_ws

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(horarios_ws)
        )
    ),
})
