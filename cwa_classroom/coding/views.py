from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def coming_soon(request):
    return render(request, 'coding/coming_soon.html', {
        'subject_name': 'Coding',
        'subject_color': '#8b5cf6',
    })
