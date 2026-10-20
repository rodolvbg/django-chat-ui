from django.contrib import admin
from django.urls import include, path
from shop import views

urlpatterns = [
    path("", views.home, name="home"),
    path("inbox/", views.inbox, name="inbox"),
    path("chat/", include("django_chat_ui.urls")),
    path("admin/", admin.site.urls),
]
