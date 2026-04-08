import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def render_markdown(value):
    """Render a Markdown string to safe HTML."""
    if not value:
        return ''
    html = markdown.markdown(
        value,
        extensions=['fenced_code', 'tables', 'toc', 'nl2br'],
    )
    return mark_safe(html)
