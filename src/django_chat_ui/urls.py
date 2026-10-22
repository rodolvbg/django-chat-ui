"""Include them where the chat lives — its homeserver's base URL:

    path("chat/", include("django_chat_ui.urls")),

and any Matrix client (Element, matrix-js-sdk…) can use
``https://<site>/chat`` as its homeserver.
"""

from django.urls import path, re_path

from . import views

app_name = "django_chat_ui"

C = "_matrix/client/v3/"
ROOM = C + "rooms/<str:room>/"
USER = C + "user/<str:user>/"
MEDIA = "_matrix/media/v3/"
AUTHENTICATED = "_matrix/client/v1/media/"

urlpatterns = [
    path("_matrix/client/versions", views.versions, name="versions"),
    path(C + "login", views.login, name="login"),
    path(C + "logout", views.logout, name="logout"),
    path(C + "logout/all", views.logout_all, name="logout_all"),
    path(C + "account/whoami", views.whoami, name="whoami"),
    path(C + "capabilities", views.capabilities, name="capabilities"),
    path(C + "pushrules/", views.pushrules, name="pushrules"),
    path(C + "sync", views.sync_view, name="sync"),
    path(C + "joined_rooms", views.joined_rooms, name="joined_rooms"),
    path(C + "createRoom", views.create_room, name="create_room"),
    path(C + "profile/<str:user>", views.profile, name="profile"),
    path(C + "profile/<str:user>/<str:field>", views.profile, name="profile_field"),
    path(USER + "filter", views.create_filter, name="create_filter"),
    path(USER + "filter/<str:filter_id>", views.get_filter, name="filter"),
    path(USER + "account_data/<str:type>", views.account_data, name="account_data"),
    path(
        USER + "rooms/<str:room>/account_data/<str:type>",
        views.room_account_data,
        name="room_account_data",
    ),
    path(ROOM + "send/<str:type>/<str:txn>", views.send, name="send"),
    path(ROOM + "redact/<str:event>/<str:txn>", views.redact, name="redact"),
    path(ROOM + "messages", views.messages, name="messages"),
    path(ROOM + "event/<str:event>", views.get_event, name="event"),
    path(ROOM + "state", views.state, name="state"),
    path(ROOM + "state/<str:type>", views.state_event, name="state_event"),
    path(ROOM + "state/<str:type>/", views.state_event),
    path(ROOM + "state/<str:type>/<str:key>", views.state_event, name="state_key"),
    path(ROOM + "members", views.members, name="members"),
    path(ROOM + "joined_members", views.joined_members, name="joined_members"),
    path(ROOM + "typing/<str:user>", views.typing, name="typing"),
    path(ROOM + "receipt/<str:kind>/<str:event>", views.receipt, name="receipt"),
    path(ROOM + "read_markers", views.read_markers, name="read_markers"),
    path(ROOM + "leave", views.leave, name="leave"),
    path(MEDIA + "upload", views.upload, name="upload"),
    path(MEDIA + "config", views.media_config),
    path(AUTHENTICATED + "config", views.media_config, name="media_config"),
    path(
        AUTHENTICATED + "download/<str:server>/<str:media_id>",
        views.download,
        name="download",
    ),
    path(
        AUTHENTICATED + "download/<str:server>/<str:media_id>/<str:name>",
        views.download,
        name="download_as",
    ),
    path(AUTHENTICATED + "thumbnail/<str:server>/<str:media_id>", views.download),
    path(MEDIA + "download/<str:server>/<str:media_id>", views.download),
    path(MEDIA + "download/<str:server>/<str:media_id>/<str:name>", views.download),
    path(MEDIA + "thumbnail/<str:server>/<str:media_id>", views.download),
    re_path(r"^_matrix/(?P<path>.*)$", views.unrecognized),
]
