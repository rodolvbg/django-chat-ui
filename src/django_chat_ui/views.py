"""The protocol over HTTP (docs/protocol.md, section 10): the stream of
events, the commands, and attachments."""

from __future__ import annotations

import json
import mimetypes
from typing import Any

from django.core.handlers.asgi import ASGIRequest
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    JsonResponse,
    StreamingHttpResponse,
)
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import commands, stream
from .backend import get_backend
from .models import AbstractParticipant, Attachment
from .protocol import ProtocolError, frame

MAX_FRAMES = 20

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


def forbidden() -> JsonResponse:
    error = ProtocolError("unauthorized", _("Log in to chat."))
    return JsonResponse(
        [frame("error", {**error.data(), "fatal": True})], safe=False, status=403
    )


def seq(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


@never_cache
@require_GET
def events(request: HttpRequest) -> HttpResponse | StreamingHttpResponse:
    """``GET events``: Server-Sent Events (10.1), or, asked for JSON, the
    events after ``?after=`` at once, for polling (10.3)."""
    backend = get_backend()
    participant = backend.get_participant(request)
    if participant is None:
        return forbidden()
    after = seq(request.GET.get("after"))
    if after is None:
        after = seq(request.headers.get("Last-Event-ID"))
    reader = stream.Reader(
        backend, participant, after, commands.client_capabilities(request)
    )

    if "text/event-stream" not in request.headers.get("Accept", ""):
        frames = reader.read() if after is not None else []
        return JsonResponse({"frames": frames, "seq": reader.after})

    body = (
        stream.aevents(reader)
        if isinstance(request, ASGIRequest)
        else stream.events(reader)
    )
    response = StreamingHttpResponse(body, content_type="text/event-stream")
    response["X-Accel-Buffering"] = "no"  # nginx: send each event at once
    return response


@never_cache
@require_POST
def commands_view(request: HttpRequest) -> JsonResponse:
    """``POST commands``: one frame or a list; answers with the frames that
    answer them (7.4), in order."""
    backend = get_backend()
    participant = backend.get_participant(request)
    if participant is None:
        return forbidden()
    try:
        body = json.loads(request.body)
    except ValueError:
        error = ProtocolError("bad_request", _("The body isn't JSON."))
        return JsonResponse([frame("error", error.data())], safe=False, status=400)
    frames = body if isinstance(body, list) else [body]
    if len(frames) > MAX_FRAMES:
        error = ProtocolError("too_large", _("Too many commands at once."))
        return JsonResponse([frame("error", error.data())], safe=False, status=400)
    answers = []
    for raw in frames:
        answers.extend(commands.handle(backend, request, participant, raw))
    return JsonResponse(answers, safe=False)


def upload_error(error: ProtocolError, status: int) -> JsonResponse:
    return JsonResponse({"error": error.data()}, status=status)


@never_cache
@require_POST
def upload(request: HttpRequest) -> JsonResponse:
    """``POST uploads`` (``conversation``, ``file``): stores a file for a
    conversation that allows it, and answers with its part, to send."""
    backend = get_backend()
    participant = backend.get_participant(request)
    if participant is None:
        return forbidden()
    pk = request.POST.get("conversation", "")
    conversation = (
        backend.conversations(participant).filter(pk=pk).first()
        if pk.isdigit()
        else None
    )
    file = request.FILES.get("file")
    if conversation is None or file is None:
        error = ProtocolError("bad_request", _("Send a file, for a conversation."))
        return upload_error(error, 400)

    allowed = conversation.capabilities.get("attachments") or {}
    name = (file.name or "file")[-255:]
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    kind = mime.split("/")[0]
    type = kind if kind in {"image", "video", "audio"} and mime in INLINE else "file"
    if type not in allowed.get("types", []):
        type = "file"
    if type not in allowed.get("types", []):
        error = ProtocolError(
            "unsupported", _("Files of this type can't be sent here.")
        )
        return upload_error(error, 400)
    limit = allowed.get("maxSize") or backend.max_upload_size
    if (file.size or 0) > min(limit, backend.max_upload_size):
        return upload_error(ProtocolError("too_large", _("The file is too big.")), 413)

    attachment = Attachment.objects.create(
        conversation=conversation,
        uploader=participant,
        file=file,
        name=name,
        mime=mime,
        size=file.size,
    )
    return JsonResponse(commands.attachment_part(attachment, type))


@require_GET
def download(request: HttpRequest, pk: int, name: str) -> FileResponse:
    """An attachment, only for those who see its conversation."""
    backend = get_backend()
    participant: AbstractParticipant | None = backend.get_participant(request)
    if participant is None:
        raise Http404
    visible = backend.conversations(participant).values("pk")
    attachment = Attachment.objects.filter(pk=pk, conversation__in=visible).first()
    if attachment is None:
        raise Http404
    inline = attachment.mime in INLINE
    response = FileResponse(
        attachment.file.open("rb"),
        as_attachment=not inline,
        filename=attachment.name,
        content_type=attachment.mime if inline else "application/octet-stream",
    )
    # Never run what someone uploaded, whatever it says it is.
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response
