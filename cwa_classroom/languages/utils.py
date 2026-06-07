CANVAS_CONFIG = {
    'latin':      {'line_height': 100, 'descender': 30, 'lines': 4},
    'sinhala':    {'line_height': 130, 'descender': 0,  'lines': 3},
    'tamil':      {'line_height': 120, 'descender': 0,  'lines': 3},
    'devanagari': {'line_height': 120, 'descender': 0,  'lines': 3},
    'arabic':     {'line_height': 110, 'descender': 25, 'lines': 3},
    'cjk':        {'line_height': 130, 'descender': 0,  'lines': 2},
}
DEFAULT_CONFIG = {'line_height': 65, 'descender': 20, 'lines': 3}

# Script type → (Google Fonts query param, CSS font-family name)
FONT_MAP = {
    'latin':      ('', 'sans-serif'),
    'sinhala':    ('Noto+Sans+Sinhala:ital,wght@0,400;0,700', 'Noto Sans Sinhala'),
    'tamil':      ('Noto+Sans+Tamil:ital,wght@0,400;0,700', 'Noto Sans Tamil'),
    'devanagari': ('Noto+Sans+Devanagari:ital,wght@0,400;0,700', 'Noto Sans Devanagari'),
    'arabic':     ('Noto+Naskh+Arabic:wght@400;700', 'Noto Naskh Arabic'),
    'cjk':        ('Noto+Sans+SC:wght@400;700', 'Noto Sans SC'),
}


# Language code → BCP-47 tag for Web Speech API SpeechSynthesis
TTS_LANG_MAP = {
    'en': 'en-US',
    'si': 'si-LK',
    'ta': 'ta-IN',
    'hi': 'hi-IN',
    'ar': 'ar-SA',
    'zh': 'zh-CN',
}


def get_canvas_config(script_type: str) -> dict:
    return CANVAS_CONFIG.get(script_type, DEFAULT_CONFIG)


def get_font_info(script_type: str) -> tuple[str, str]:
    """Return (google_fonts_query, css_font_family) for the given script type."""
    return FONT_MAP.get(script_type, ('', 'sans-serif'))


def get_tts_lang_code(language_code: str) -> str:
    """Return BCP-47 TTS language tag for Web Speech API, defaulting to en-NZ."""
    return TTS_LANG_MAP.get(language_code, 'en-NZ')
