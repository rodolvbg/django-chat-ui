"""The Matrix Client-Server API (https://spec.matrix.org/v1.11/client-server-api/):
what of it this package serves (docs/protocol.md, section 3), at
``<base>/_matrix/…`` where its URLs are included.

A request is authenticated by an access token (``POST /login``: any Matrix
client), or by the site's session (this package's components, on the same
site; then unsafe methods need its CSRF token).
"""

from __future__ import annotations

import functools
import json
import mimetypes
import secrets
from collections.abc import Callable
from typing import Any, cast

from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    JsonResponse,
)
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from . import services, sync
from .backend import ChatBackend, get_backend
from .matrix import (
    CONVERSATION,
    NS,
    ROOM_VERSION,
    VERSIONS,
    MatrixError,
    client_event,
    mxc,
    parse_room,
    parse_user,
    room_id,
    server_name,
    user_id,
)
from .models import (
    AbstractConversation,
    AbstractParticipant,
    AccessToken,
    AccountData,
    Media,
    Membership,
    RoomEvent,
    RoomState,
    SyncFilter,
    get_participant_model,
    hash_token,
)
from .rules import Rules, target

#: Served inline (shown in the page); anything else is downloaded.
INLINE = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "video/mp4",
    "video/webm",
    "audio/mpeg",
    "audio/ogg",
    "audio/webm",
    "audio/mp4",
}

SAFE = {"GET", "HEAD", "OPTIONS"}


def cors(response: HttpResponseBase) -> HttpResponseBase:
    """What the specification asks of every response, for clients of other
    origins (which authenticate with a token: cookies aren't sent with ``*``)."""
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response["Access-Control-Allow-Headers"] = (
        "X-Requested-With, Content-Type, Authorization"
    )
    return response


def csrf_failed(request: HttpRequest) -> bool:
    middleware = CsrfViewMiddleware(lambda request: HttpResponse())
    middleware.process_request(request)
    return middleware.process_view(request, None, (), {}) is not None  # type: ignore[arg-type]


def authenticate(
    request: HttpRequest, backend: ChatBackend
) -> tuple[AbstractParticipant, AccessToken | None]:
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.startswith("Bearer ") else None
    token = token or request.GET.get("access_token")
    if token:
        found = (
            AccessToken.objects.filter(digest=hash_token(token))
            .select_related("participant")
            .first()
        )
        if found is None:
            raise MatrixError("M_UNKNOWN_TOKEN", _("Log in again."))
        return found.participant, found
    participant = backend.get_participant(request)
    if participant is None:
        raise MatrixError("M_MISSING_TOKEN", _("Log in to chat."))
    if request.method not in SAFE and csrf_failed(request):
        raise MatrixError("M_FORBIDDEN", _("The CSRF token is missing or wrong."))
    return participant, None


class Context:
    """One request to the API: who makes it, and its JSON."""

    def __init__(self, request: HttpRequest, *, auth: bool = True):
        self.request = request
        self.backend = get_backend()
        self.token: AccessToken | None = None
        if auth:
            self.participant, self.token = authenticate(request, self.backend)

    @functools.cached_property
    def json(self) -> dict[str, Any]:
        try:
            data = json.loads(self.request.body or b"{}")
        except ValueError:
            raise MatrixError("M_NOT_JSON", _("The body isn't JSON.")) from None
        if not isinstance(data, dict):
            raise MatrixError("M_BAD_JSON", _("The body must be an object."))
        return data

    def conversation(self, room: str) -> AbstractConversation:
        """A room the participant is in; else, as the specification says,
        forbidden (whether it exists or not)."""
        pk = parse_room(room)
        found = (
            self.backend.conversations(self.participant).filter(pk=pk).first()
            if pk
            else None
        )
        if found is None:
            raise MatrixError("M_FORBIDDEN", _("You aren't in this room."))
        return found

    def me(self, user: str) -> None:
        """A path's ``userId`` that must be the participant's."""
        if user != user_id(self.participant):
            raise MatrixError("M_FORBIDDEN", _("That isn't you."))


View = Callable[..., Any]


def endpoint(*methods: str, auth: bool = True) -> Callable[[View], View]:
    """An endpoint of the API: its methods, its errors as Matrix has them,
    its answers as JSON, CORS."""

    def decorate(view: View) -> View:
        @csrf_exempt
        @never_cache
        @functools.wraps(view)
        def handle(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
            if request.method == "OPTIONS":
                return cors(HttpResponse())
            try:
                if request.method not in methods:
                    raise MatrixError("M_UNRECOGNIZED", _("Unrecognized request."), 405)
                result = view(Context(request, auth=auth), *args, **kwargs)
            except MatrixError as error:
                return cors(error.response())
            if not isinstance(result, HttpResponseBase):
                result = JsonResponse(result)
            return cors(result)

        return handle

    return decorate


@csrf_exempt
def unrecognized(request: HttpRequest, path: str = "") -> HttpResponseBase:
    return cors(MatrixError("M_UNRECOGNIZED", _("Unrecognized request.")).response())


# Session -------------------------------------------------------------------------


@endpoint("GET", auth=False)
def versions(ctx: Context) -> dict[str, Any]:
    return {"versions": VERSIONS, "unstable_features": {NS: True}}


@endpoint("GET", "POST", auth=False)
def login(ctx: Context) -> dict[str, Any]:
    """Log in with a user of the site and their password (``m.login.password``)."""
    if ctx.request.method == "GET":
        return {"flows": [{"type": "m.login.password"}]}
    data = ctx.json
    if data.get("type") != "m.login.password":
        raise MatrixError("M_UNKNOWN", _("Only passwords can log in."))
    identifier = data.get("identifier")
    user = identifier.get("user") if isinstance(identifier, dict) else data.get("user")
    password = data.get("password")
    if not isinstance(user, str) or not isinstance(password, str):
        raise MatrixError("M_BAD_JSON", _("A user and their password, please."))
    pk = parse_user(user)
    if pk is not None:
        # Their Matrix ID: the site's username of its participant.
        found = get_participant_model().objects.filter(pk=pk).select_related("user")
        owner = getattr(found.first(), "user", None)
        user = owner.get_username() if owner is not None else ""
    participant = ctx.backend.login(ctx.request, user, password)
    if participant is None:
        raise MatrixError("M_FORBIDDEN", _("Wrong user or password."))
    token = secrets.token_urlsafe(32)
    device = data.get("device_id")
    if not isinstance(device, str) or not device:
        device = secrets.token_hex(5).upper()
    AccessToken.objects.create(
        participant=participant, digest=hash_token(token), device_id=device[:255]
    )
    return {
        "user_id": user_id(participant),
        "access_token": token,
        "device_id": device,
        "home_server": server_name(),
    }


@endpoint("POST")
def logout(ctx: Context) -> dict[str, Any]:
    if ctx.token is not None:
        ctx.token.delete()
    return {}


@endpoint("POST")
def logout_all(ctx: Context) -> dict[str, Any]:
    AccessToken.objects.filter(participant=ctx.participant).delete()
    return {}


@endpoint("GET")
def whoami(ctx: Context) -> dict[str, Any]:
    data: dict[str, Any] = {"user_id": user_id(ctx.participant), "is_guest": False}
    if ctx.token is not None:
        data["device_id"] = ctx.token.device_id
    return data


@endpoint("GET")
def capabilities(ctx: Context) -> dict[str, Any]:
    return {
        "capabilities": {
            "m.change_password": {"enabled": False},
            "m.set_displayname": {"enabled": False},
            "m.set_avatar_url": {"enabled": False},
            "m.3pid_changes": {"enabled": False},
            "m.room_versions": {
                "default": ROOM_VERSION,
                "available": {ROOM_VERSION: "stable"},
            },
        }
    }


@endpoint("GET")
def pushrules(ctx: Context) -> dict[str, Any]:
    """No push rules (nothing is pushed): clients ask for them anyway."""
    rules: dict[str, list] = {
        kind: [] for kind in ("override", "content", "room", "sender", "underride")
    }
    return {"global": rules}


@endpoint("POST")
def create_filter(ctx: Context, user: str) -> dict[str, Any]:
    ctx.me(user)
    created = SyncFilter.objects.create(
        participant=ctx.participant, definition=ctx.json
    )
    return {"filter_id": str(created.pk)}


@endpoint("GET")
def get_filter(ctx: Context, user: str, filter_id: str) -> dict[str, Any]:
    ctx.me(user)
    found = (
        SyncFilter.objects.filter(pk=filter_id, participant=ctx.participant).first()
        if filter_id.isdigit()
        else None
    )
    if found is None:
        raise MatrixError("M_NOT_FOUND", _("There is no such filter."))
    return found.definition


def _account_data(ctx: Context, conversation: Any, type: str) -> dict[str, Any]:
    if ctx.request.method == "PUT":
        AccountData.objects.update_or_create(
            participant=ctx.participant,
            conversation=conversation,
            type=type,
            defaults={"content": ctx.json},
        )
        services.entry(
            "account_data",
            conversation=conversation,
            recipient=ctx.participant,
            type=type,
            data=ctx.json,
        )
        return {}
    found = AccountData.objects.filter(
        participant=ctx.participant, conversation=conversation, type=type
    ).first()
    if found is None:
        raise MatrixError("M_NOT_FOUND", _("There is no such data."))
    return found.content


@endpoint("GET", "PUT")
def account_data(ctx: Context, user: str, type: str) -> dict[str, Any]:
    ctx.me(user)
    return _account_data(ctx, None, type)


@endpoint("GET", "PUT")
def room_account_data(ctx: Context, user: str, room: str, type: str) -> dict[str, Any]:
    ctx.me(user)
    return _account_data(ctx, ctx.conversation(room), type)


@endpoint("GET")
def profile(ctx: Context, user: str, field: str = "") -> dict[str, Any]:
    """Someone's name, if they share a room with whoever asks (or are them)."""
    pk = parse_user(user)
    visible = ctx.backend.conversations(ctx.participant).values("pk")
    found = (
        get_participant_model()
        .objects.filter(pk=pk)
        .filter(memberships__conversation__in=visible)
        .first()
        if pk
        else None
    )
    if found is None and pk == str(ctx.participant.pk):
        found = ctx.participant
    if found is None:
        raise MatrixError("M_NOT_FOUND", _("There is no such user."))
    data = {"displayname": found.name} if found.name else {}
    if field:
        if field not in data:
            raise MatrixError("M_NOT_FOUND", _("They have no such field."))
        return {field: data[field]}
    return data


# Sync ----------------------------------------------------------------------------


def _sync_start(request: HttpRequest) -> sync.Sync:
    backend = get_backend()
    participant, _ = authenticate(request, backend)
    since = (
        None if request.GET.get("full_state") == "true" else request.GET.get("since")
    )
    return sync.Sync(
        backend,
        participant,
        sync.position(since),
        sync.filter_limit(participant, request.GET.get("filter")),
    )


async def sync_view(request: HttpRequest) -> HttpResponseBase:
    """``GET /sync``: long polling, ``timeout`` milliseconds at most (and
    ``SYNC_TIMEOUT`` seconds). Under ASGI, waiting holds no thread."""
    response = await _sync(request)
    add_never_cache_headers(response)
    return cors(response)


# Django < 5.0's decorators don't take a coroutine: by hand.
sync_view.csrf_exempt = True  # type: ignore[attr-defined]


async def _sync(request: HttpRequest) -> HttpResponseBase:
    if request.method == "OPTIONS":
        return HttpResponse()
    try:
        if request.method != "GET":
            raise MatrixError("M_UNRECOGNIZED", _("Unrecognized request."), 405)
        syncing = await sync_to_async(_sync_start)(request)
    except MatrixError as error:
        return error.response()
    try:
        timeout = max(0.0, float(request.GET.get("timeout", 0)) / 1000)
    except ValueError:
        timeout = 0.0
    timeout = min(timeout, sync.setting("SYNC_TIMEOUT", 30))
    return JsonResponse(await sync.wait(syncing, timeout))


# Rooms ---------------------------------------------------------------------------


@endpoint("GET")
def joined_rooms(ctx: Context) -> dict[str, Any]:
    rooms = ctx.backend.conversations(ctx.participant).distinct()
    return {"joined_rooms": [room_id(c) for c in rooms]}


@endpoint("POST")
def create_room(ctx: Context) -> dict[str, Any]:
    """Start a conversation with those it invites (none: with the support
    team, as the "contact us" widget does); its channel, in the
    ``initial_state`` of this package's ``conversation``."""
    data = ctx.json
    invite = data.get("invite", [])
    if not isinstance(invite, list) or not all(isinstance(i, str) for i in invite):
        raise MatrixError("M_BAD_JSON", _("invite must list user IDs."))
    wanted = {parse_user(i) for i in invite} - {str(ctx.participant.pk)}
    if None in wanted:
        raise MatrixError("M_NOT_FOUND", _("There is no such participant."))
    others = list(get_participant_model().objects.filter(pk__in=wanted))
    if len(others) != len(wanted):
        raise MatrixError("M_NOT_FOUND", _("There is no such participant."))
    channel = "web"
    for state in data.get("initial_state") or []:
        if isinstance(state, dict) and state.get("type") == CONVERSATION:
            channel = (state.get("content") or {}).get("channel") or channel
    if not isinstance(channel, str) or len(channel) > 64:
        raise MatrixError("M_BAD_JSON", _("That isn't a channel."))
    if not ctx.backend.can_start(ctx.participant, others, channel):
        raise MatrixError("M_FORBIDDEN", _("You can't start that conversation."))
    conversation = ctx.backend.start(ctx.request, ctx.participant, others, channel)
    return {"room_id": room_id(conversation)}


def _sent(event: RoomEvent) -> dict[str, Any]:
    return {"event_id": event.event_id}


@endpoint("PUT")
def send(ctx: Context, room: str, type: str, txn: str) -> dict[str, Any]:
    """Send an event; a transaction sent again isn't sent twice."""
    conversation = ctx.conversation(room)
    existing = conversation.events.filter(sender=ctx.participant, txn_id=txn).first()
    if existing is not None:
        return _sent(existing)
    checked = Rules(ctx.backend, ctx.participant, conversation).check(type, ctx.json)
    ctx.backend.before_send(
        ctx.request, conversation, ctx.participant, type, checked.content
    )
    try:
        event = services.send(
            conversation, ctx.participant, checked.content, type=type, txn_id=txn
        )
    except IntegrityError:  # The same transaction, at the same time.
        return _sent(conversation.events.get(sender=ctx.participant, txn_id=txn))
    backend = ctx.backend
    if checked.action is not None:
        message, button = checked.action
        backend.run_hook(
            backend.on_action, ctx.request, ctx.participant, message, button
        )
    elif type == "m.room.message" and event.rel_type != "m.replace":
        backend.run_hook(backend.on_message, ctx.request, event)
    elif type in backend.event_types:
        backend.run_hook(backend.on_event, ctx.request, event)
    return _sent(event)


@endpoint("PUT")
def redact(ctx: Context, room: str, event: str, txn: str) -> dict[str, Any]:
    conversation = ctx.conversation(room)
    existing = conversation.events.filter(sender=ctx.participant, txn_id=txn).first()
    if existing is not None:
        return _sent(existing)
    redacted = target(conversation, event)
    if redacted.redacted_by_id:
        return _sent(RoomEvent.objects.get(pk=redacted.redacted_by_id))
    Rules(ctx.backend, ctx.participant, conversation).redaction(redacted)
    reason = ctx.json.get("reason")
    redaction = services.redact(
        redacted,
        ctx.participant,
        reason if isinstance(reason, str) else "",
        txn_id=txn,
    )
    return _sent(redaction)


@endpoint("GET")
def messages(ctx: Context, room: str) -> dict[str, Any]:
    conversation = ctx.conversation(room)
    try:
        limit = int(ctx.request.GET.get("limit", 10))
    except ValueError:
        limit = 10
    return sync.messages(
        conversation,
        ctx.participant,
        ctx.request.GET.get("from"),
        ctx.request.GET.get("dir", "b"),
        max(1, min(limit, sync.MAX_LIMIT)),
    )


@endpoint("GET")
def get_event(ctx: Context, room: str, event: str) -> dict[str, Any]:
    return client_event(target(ctx.conversation(room), event), viewer=ctx.participant)


@endpoint("GET")
def state(ctx: Context, room: str) -> Any:
    events = sync.current_state(ctx.conversation(room))
    return JsonResponse(
        [client_event(e, viewer=ctx.participant) for e in events], safe=False
    )


@endpoint("GET", "PUT")
def state_event(ctx: Context, room: str, type: str, key: str = "") -> dict[str, Any]:
    conversation = ctx.conversation(room)
    if ctx.request.method == "PUT":
        # The server's to change (power levels: state_default 100).
        raise MatrixError("M_FORBIDDEN", _("The state of this room is the server's."))
    found = (
        RoomState.objects.filter(conversation=conversation, type=type, state_key=key)
        .select_related("event")
        .first()
    )
    if found is None:
        raise MatrixError("M_NOT_FOUND", _("There is no such state."))
    return found.event.content


@endpoint("GET")
def members(ctx: Context, room: str) -> dict[str, Any]:
    events = sync.current_state(ctx.conversation(room))
    return {
        "chunk": [
            client_event(e, viewer=ctx.participant)
            for e in events
            if e.type == "m.room.member"
        ]
    }


@endpoint("GET")
def joined_members(ctx: Context, room: str) -> dict[str, Any]:
    conversation = ctx.conversation(room)
    joined = {}
    for membership in Membership.objects.filter(
        conversation=conversation
    ).select_related("participant"):
        name = membership.participant.name
        joined[user_id(membership.participant)] = {"display_name": name} if name else {}
    return {"joined": joined}


@endpoint("PUT")
def typing(ctx: Context, room: str, user: str) -> dict[str, Any]:
    conversation = ctx.conversation(room)
    ctx.me(user)
    # Where the conversation doesn't show it, said and ignored.
    if conversation.capabilities.get("typing"):
        timeout = ctx.json.get("timeout", 30000)
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            timeout = 30000
        services.typing(
            conversation, ctx.participant, bool(ctx.json.get("typing")), timeout
        )
    return {}


def _read(
    ctx: Context, conversation: AbstractConversation, kind: str, event: Any
) -> None:
    until = target(conversation, event)
    if kind == "m.fully_read":
        content = {"event_id": until.event_id}
        AccountData.objects.update_or_create(
            participant=ctx.participant,
            conversation=conversation,
            type="m.fully_read",
            defaults={"content": content},
        )
        services.entry(
            "account_data",
            conversation=conversation,
            recipient=ctx.participant,
            type="m.fully_read",
            data=content,
        )
    elif kind in {"m.read", "m.read.private"}:
        services.read(conversation, ctx.participant, until, public=kind == "m.read")
    else:
        raise MatrixError("M_INVALID_PARAM", _("Unknown receipt type."))


@endpoint("POST")
def receipt(ctx: Context, room: str, kind: str, event: str) -> dict[str, Any]:
    _read(ctx, ctx.conversation(room), kind, event)
    return {}


@endpoint("POST")
def read_markers(ctx: Context, room: str) -> dict[str, Any]:
    conversation = ctx.conversation(room)
    for kind in ("m.fully_read", "m.read", "m.read.private"):
        if ctx.json.get(kind):
            _read(ctx, conversation, kind, ctx.json[kind])
    return {}


@endpoint("POST")
def leave(ctx: Context, room: str) -> dict[str, Any]:
    services.remove_participant(ctx.conversation(room), ctx.participant)
    return {}


# Media ---------------------------------------------------------------------------


@endpoint("GET")
def media_config(ctx: Context) -> dict[str, Any]:
    return {"m.upload.size": ctx.backend.max_upload_size}


@endpoint("POST")
def upload(ctx: Context) -> dict[str, Any]:
    """``POST /upload?filename=``: the file is the body. It's sent to a
    conversation (and checked against what it takes) in a message."""
    limit = ctx.backend.max_upload_size
    try:
        length = int(ctx.request.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length > limit:
        raise MatrixError("M_TOO_LARGE", _("The file is too big."))
    data = ctx.request.read(limit + 1)
    if len(data) > limit:
        raise MatrixError("M_TOO_LARGE", _("The file is too big."))
    name = (ctx.request.GET.get("filename") or "file")[-255:]
    mime = (
        mimetypes.guess_type(name)[0]
        or ctx.request.headers.get("Content-Type", "").split(";")[0].strip()
        or "application/octet-stream"
    )
    media = Media(
        uploader=cast(Any, ctx.participant), name=name, mime=mime[:100], size=len(data)
    )
    media.file.save(name, ContentFile(data), save=False)
    media.save()
    return {"content_uri": mxc(media.media_id)}


@endpoint("GET")
def download(ctx: Context, server: str, media_id: str, name: str = "") -> FileResponse:
    """A file, only for its uploader and those who see its conversation."""
    visible = ctx.backend.conversations(ctx.participant).values("pk")
    found = (
        Media.objects.filter(media_id=media_id)
        .exclude(conversation=None)
        .filter(conversation__in=visible)
        .first()
        or Media.objects.filter(media_id=media_id, uploader=ctx.participant).first()
        if server == server_name()
        else None
    )
    if found is None:
        raise MatrixError("M_NOT_FOUND", _("There is no such file."))
    inline = found.mime in INLINE
    response = FileResponse(
        found.file.open("rb"),
        as_attachment=not inline,
        filename=name or found.name,
        content_type=found.mime if inline else "application/octet-stream",
    )
    # Never run what someone uploaded, whatever it says it is.
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    return response
