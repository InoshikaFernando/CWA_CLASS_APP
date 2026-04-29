"""Views for question upload functionality."""

import json
import os
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, FileResponse, Http404
from django.contrib import messages

_SAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), 'management', 'commands', 'samples'
)

from .forms import QuestionUploadForm
from .permissions import require_upload_permission, get_user_role
from .upload_service import QuestionUploadService


@login_required
@require_upload_permission
@require_http_methods(["GET", "POST"])
def upload_questions(request):
    """Handle question upload form and processing.

    GET: Display upload form
    POST: Process file upload
    """
    if request.method == 'POST':
        form = QuestionUploadForm(request.POST, request.FILES)

        if form.is_valid():
            subject = form.cleaned_data['subject']
            file_format = form.cleaned_data['file_format']
            file_obj = form.cleaned_data['file']

            # Create upload service
            service = QuestionUploadService(request.user, subject_type=subject)

            # Reset file pointer
            file_obj.seek(0)

            # Upload
            result = service.upload_file(file_obj, file_format)

            # Store result in session for results page
            request.session['upload_result'] = result

            # Show summary message
            if result['status'] == 'success':
                messages.success(
                    request,
                    f"Successfully uploaded {result['created']} question(s)"
                )
            elif result['status'] == 'warning':
                messages.warning(
                    request,
                    f"Upload complete: {result['created']} created, "
                    f"{result['skipped']} skipped"
                )
            else:
                messages.error(
                    request,
                    f"Upload failed: {', '.join(result['errors'])}"
                )

            # Redirect to results page
            return redirect('brainbuzz:upload_results')

        else:
            # Form validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    else:
        form = QuestionUploadForm()

    # Determine role for template display
    role = get_user_role(request.user)

    context = {
        'form': form,
        'user_role': role,
        'role_description': _get_role_description(role),
    }

    return render(request, 'brainbuzz/upload_form.html', context)


@login_required
@require_http_methods(["GET"])
def upload_results(request):
    """Display results of most recent upload."""
    result = request.session.get('upload_result')

    if not result:
        messages.info(request, "No recent upload found")
        return redirect('brainbuzz:upload_questions')

    # Clear result from session
    del request.session['upload_result']
    request.session.save()

    role = get_user_role(request.user)

    context = {
        'result': result,
        'user_role': role,
    }

    return render(request, 'brainbuzz/upload_results.html', context)


@login_required
@require_upload_permission
@require_http_methods(["POST"])
def api_upload_questions(request):
    """API endpoint for question uploads (JSON request/response).

    POST JSON with keys:
        - subject: 'maths' or 'coding'
        - file_format: 'json', 'csv', 'excel'
        - file_content: base64-encoded file content (optional)
        - file: Uploaded file (if not using file_content)
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    subject = data.get('subject', 'maths')
    file_format = data.get('file_format', 'json')

    # Validate subject
    if subject not in ('maths', 'coding'):
        return JsonResponse({'error': f"Invalid subject: {subject}"}, status=400)

    # Validate format
    if file_format not in ('json', 'csv', 'excel'):
        return JsonResponse({'error': f"Invalid file_format: {file_format}"}, status=400)

    # Get file object
    if 'file' in request.FILES:
        file_obj = request.FILES['file']
    else:
        return JsonResponse({'error': 'No file provided'}, status=400)

    # Create upload service and process
    service = QuestionUploadService(request.user, subject_type=subject)
    file_obj.seek(0)
    result = service.upload_file(file_obj, file_format)

    return JsonResponse(result)


@login_required
@require_http_methods(["GET"])
def api_questions_list(request):
    """API endpoint to list questions visible to user.

    Query parameters:
        - subject: 'maths' or 'coding' (required)
        - topic: Topic name filter (optional)
        - level: Level number filter (optional, maths only)
        - question_type: Question type filter (optional)
        - page: Page number (default 1)
        - limit: Results per page (default 20)
    """
    subject = request.GET.get('subject', 'maths')
    topic_filter = request.GET.get('topic', '').strip()
    level_filter = request.GET.get('level', '').strip()
    type_filter = request.GET.get('question_type', '').strip()
    page = int(request.GET.get('page', 1))
    limit = int(request.GET.get('limit', 20))

    # Validate subject
    if subject not in ('maths', 'coding'):
        return JsonResponse({'error': 'Invalid subject'}, status=400)

    try:
        if subject == 'maths':
            from maths.models import Question

            # Get visible questions using custom manager
            queryset = Question.objects.visible_to(request.user)

            # Apply filters
            if topic_filter:
                queryset = queryset.by_topic(topic_filter)

            if type_filter:
                queryset = queryset.by_type(type_filter)

            if level_filter:
                queryset = queryset.by_level(int(level_filter))

            # Paginate
            total = queryset.count()
            start = (page - 1) * limit
            end = start + limit
            questions = queryset[start:end]

            # Serialize
            data = [
                {
                    'id': q.id,
                    'question_text': q.question_text,
                    'question_type': q.question_type,
                    'difficulty': q.difficulty,
                    'topic': q.topic.name,
                    'level': q.level.level_number,
                    'answer_count': q.answers.count(),
                }
                for q in questions
            ]

            return JsonResponse({
                'subject': subject,
                'total': total,
                'page': page,
                'limit': limit,
                'pages': (total + limit - 1) // limit,
                'questions': data,
            })

        else:  # coding
            from coding.models import CodingExercise

            # Get visible exercises using custom manager
            queryset = CodingExercise.objects.visible_to(request.user)

            # Apply filters
            if topic_filter:
                queryset = queryset.by_topic(topic_filter)

            if type_filter:
                queryset = queryset.by_type(type_filter)

            # Paginate
            total = queryset.count()
            start = (page - 1) * limit
            end = start + limit
            exercises = queryset[start:end]

            # Serialize
            data = [
                {
                    'id': e.id,
                    'title': e.title,
                    'question_type': e.question_type,
                    'difficulty': e.difficulty,
                    'topic': e.topic_level.topic.name,
                    'level': e.topic_level.level_choice,
                    'answer_count': e.answers.count(),
                }
                for e in exercises
            ]

            return JsonResponse({
                'subject': subject,
                'total': total,
                'page': page,
                'limit': limit,
                'pages': (total + limit - 1) // limit,
                'questions': data,
            })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(["GET"])
def download_sample_template(request, file_format):
    """Serve a sample question upload template file.

    Args:
        file_format: 'json', 'csv', or 'excel'
    """
    extension_map = {
        'json': ('sample_maths_questions.json', 'application/json'),
        'csv': ('sample_maths_questions.csv', 'text/csv'),
        'excel': ('sample_maths_questions.xlsx',
                  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    }

    if file_format not in extension_map:
        raise Http404(f"Unknown format: {file_format}")

    filename, content_type = extension_map[file_format]
    filepath = os.path.join(_SAMPLES_DIR, filename)

    if not os.path.exists(filepath):
        raise Http404(f"Sample file not found: {filename}")

    response = FileResponse(open(filepath, 'rb'), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _get_role_description(role: str) -> str:
    """Get human-readable description of user role."""
    descriptions = {
        'superuser': 'Super User (Global)',
        'admin': 'Institute Admin (Institute-local)',
        'teacher': 'Class Teacher (Class-local)',
        'guest': 'Guest (No upload permission)',
    }
    return descriptions.get(role, 'Unknown')
