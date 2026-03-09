from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Look up a dictionary value by key in a template."""
    if dictionary is None:
        return ''
    return dictionary.get(key, '')
