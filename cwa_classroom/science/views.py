from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def coming_soon(request):
    return render(request, 'science/coming_soon.html', {
        'subject_name': 'Science',
        'subject_color': '#0d9488',
    })
