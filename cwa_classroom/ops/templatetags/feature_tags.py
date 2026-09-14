"""``{% feature_enabled %}`` for templates.

    {% load feature_tags %}
    {% feature_enabled 'language' school as language_on %}
    {% if language_on %}...{% endif %}

An ``as`` variable rather than a filter, because a template that checks the
same flag three times should cost one call, and because the school has to be
passed explicitly — a filter would make it look optional, and a flag in pilot
with no school silently reads False.
"""
from django import template

from ops.flags import feature_enabled

register = template.Library()


@register.simple_tag
def feature_enabled(slug, school=None):  # noqa: F811 — the tag shadows deliberately
    from ops import flags
    return flags.feature_enabled(slug, school)
