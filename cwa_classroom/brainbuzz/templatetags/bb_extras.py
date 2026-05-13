from django import template
from brainbuzz.utils import render_question_html

register = template.Library()


@register.filter(is_safe=True)
def render_code_question(value):
    """Template filter: convert fenced code blocks in question text to HTML.

    Usage: {{ exercise.description|render_code_question }}
    """
    return render_question_html(value or '')
