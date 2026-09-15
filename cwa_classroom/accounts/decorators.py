from functools import wraps

from django.shortcuts import redirect


def student_required(view_func):
    """Block elevated roles from accumulating student answer or time-log records."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        blocked = (
            'is_teacher',
            'is_head_of_institute',
            'is_head_of_department',
            'is_institute_owner',
            'is_admin_user',
        )
        if any(getattr(request.user, flag, False) for flag in blocked):
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return _wrapped
