from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def context(request: HttpRequest) -> dict[str, int]:
    # ?poll=3000 to poll every 3 seconds instead of long polling.
    try:
        poll = int(request.GET.get("poll", 0))
    except ValueError:
        poll = 0
    return {"poll": poll}


def home(request: HttpRequest) -> HttpResponse:
    """The public site: its visitors chat through the widget."""
    return render(request, "shop/home.html", context(request))


@staff_member_required
def inbox(request: HttpRequest) -> HttpResponse:
    """The staff's inbox: every conversation they take part in."""
    return render(request, "shop/inbox.html", context(request))
