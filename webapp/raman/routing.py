from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/raman/', consumers.RamanConsumer.as_asgi()),
]