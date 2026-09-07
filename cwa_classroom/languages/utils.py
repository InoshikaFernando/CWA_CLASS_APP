CANVAS_CONFIG = {
    'latin':      {'line_height': 100, 'descender': 30, 'lines': 4},
    'sinhala':    {'line_height': 130, 'descender': 0,  'lines': 3},
    'tamil':      {'line_height': 120, 'descender': 0,  'lines': 3},
    'devanagari': {'line_height': 120, 'descender': 0,  'lines': 3},
    'arabic':     {'line_height': 110, 'descender': 25, 'lines': 3},
    'cjk':        {'line_height': 130, 'descender': 0,  'lines': 2},
    'kana':       {'line_height': 130, 'descender': 0,  'lines': 2},
    'hangul':     {'line_height': 130, 'descender': 0,  'lines': 2},
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
    'kana':       ('Noto+Sans+JP:wght@400;700', 'Noto Sans JP'),
    'hangul':     ('Noto+Sans+KR:wght@400;700', 'Noto Sans KR'),
}


# Language code → BCP-47 tag for Web Speech API SpeechSynthesis
TTS_LANG_MAP = {
    'en': 'en-NZ',
    'fr': 'fr-FR',
    'si': 'si-LK',
    'ta': 'ta-IN',
    'hi': 'hi-IN',
    'ar': 'ar-SA',
    'zh': 'zh-CN',
    'ja': 'ja-JP',
    'ko': 'ko-KR',
}


def get_canvas_config(script_type: str) -> dict:
    return CANVAS_CONFIG.get(script_type, DEFAULT_CONFIG)


def get_font_info(script_type: str) -> tuple[str, str]:
    """Return (google_fonts_query, css_font_family) for the given script type."""
    return FONT_MAP.get(script_type, ('', 'sans-serif'))


# Letter-writing only: the on-screen guide glyph must be rendered in the same
# font the server-side scorer (languages/scoring.py) rasterises its target
# glyph from, or the "correct" shape the student traces won't match the shape
# they're scored against. FONT_MAP's 'latin' entry is generic system
# sans-serif (fine for body text elsewhere), so override it here rather than
# changing FONT_MAP itself, which every other exercise type also reads.
LETTER_WRITING_FONT_MAP = {
    'latin': ('Noto+Sans:ital,wght@0,400;0,700', 'Noto Sans'),
}


def get_letter_writing_font_info(script_type: str) -> tuple[str, str]:
    """Return (google_fonts_query, css_font_family) matching scoring.py's vendored font."""
    if script_type in LETTER_WRITING_FONT_MAP:
        return LETTER_WRITING_FONT_MAP[script_type]
    return get_font_info(script_type)


def get_tts_lang_code(language_code: str) -> str:
    """Return BCP-47 TTS language tag for Web Speech API, defaulting to en-NZ."""
    return TTS_LANG_MAP.get(language_code, 'en-NZ')
