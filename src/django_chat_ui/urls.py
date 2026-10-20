"""Include them where the chat lives:

path("chat/", include("django_chat_ui.urls")),
"""

from django.urls import path

from . import views

app_name = "django_chat_ui"

urlpatterns = [
    path("events", views.events, name="events"),
    path("commands", views.commands_view, name="commands"),
    path("uploads", views.upload, name="uploads"),
    path("uploads/<int:pk>/<path:name>", views.download, name="upload"),
]
