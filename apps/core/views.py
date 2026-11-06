from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render


def painel(request):
    return render(request, "core/painel.html")


@login_not_required
def erro_403(request, exception=None):
    return render(request, "403.html", status=403)


@login_not_required
def erro_404(request, exception=None):
    return render(request, "404.html", status=404)
