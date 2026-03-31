from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """Template filter to lookup dictionary values by key"""
    if dictionary is None:
        return None
    return dictionary.get(key, None)

@register.filter
def basic_facts_level(level_number):
    """Convert Basic Facts level number (100+) to display level (1+)"""
    if level_number >= 100:
        if 100 <= level_number <= 106:  # Addition
            return level_number - 99
        elif 107 <= level_number <= 113:  # Subtraction
            return level_number - 106
        elif 114 <= level_number <= 120:  # Multiplication
            return level_number - 113
        elif 121 <= level_number <= 127:  # Division
            return level_number - 120
        elif 128 <= level_number <= 132:  # Place Value Facts
            return level_number - 127
    return level_number

@register.filter
def format_time(seconds):
    """Format seconds into mm:ss or ss format"""
    if not seconds or seconds == 0:
        return "N/A"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f"{minutes}m {remaining_seconds}s"