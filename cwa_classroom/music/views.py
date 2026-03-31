from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def coming_soon(request):
    return render(request, 'music/coming_soon.html', {
        'subject_name': 'Music',
        'subject_color': '#ec4899',
    })
