from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    """The public site: its visitors chat through the widget."""
    return render(request, "shop/home.html")


@staff_member_required
def inbox(request: HttpRequest) -> HttpResponse:
    """The staff's inbox: every conversation they take part in."""
    return render(request, "shop/inbox.html")
