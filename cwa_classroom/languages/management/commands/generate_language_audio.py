"""
Management command: generate_language_audio

Generates MP3 audio files for phonics-MCQ exercises using Google TTS (gTTS).
Targets Sinhala (si) and Tamil (ta) by default; optionally any language.

Usage:
    python manage.py generate_language_audio            # si + ta
    python manage.py generate_language_audio --lang si  # Sinhala only
    python manage.py generate_language_audio --lang ta  # Tamil only
    python manage.py generate_language_audio --lang en  # English only
    python manage.py generate_language_audio --force    # re-generate even if file exists
"""

import io
import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from languages.models import Language, LanguageExercise


# gTTS language codes (BCP-47 → gTTS tag)
GTTS_LANG_MAP = {
    'si': 'si',   # Sinhala
    'ta': 'ta',   # Tamil
    'en': 'en',   # English
    'hi': 'hi',   # Hindi
    'ar': 'ar',   # Arabic
    'zh': 'zh',   # Chinese
}


class Command(BaseCommand):
    help = 'Generate gTTS audio files for phonics-MCQ exercises (Sinhala, Tamil, etc.)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lang', type=str, default=None,
            help='Language code to generate audio for (default: si and ta). '
                 'Options: en, si, ta, hi, ar, zh',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-generate audio even if the exercise already has an audio file.',
        )

    def handle(self, *args, **options):
        try:
            from gtts import gTTS
        except ImportError:
            self.stderr.write(self.style.ERROR(
                'gTTS is not installed. Run: pip install gTTS'
            ))
            return

        lang_filter = options['lang']
        force = options['force']

        if lang_filter:
            lang_codes = [lang_filter]
        else:
            lang_codes = ['si', 'ta']   # default: the two languages without OS voices

        for code in lang_codes:
            if code not in GTTS_LANG_MAP:
                self.stderr.write(f'Unknown lang code: {code}. Available: {list(GTTS_LANG_MAP.keys())}')
                continue

            gtts_code = GTTS_LANG_MAP[code]

            try:
                language = Language.objects.get(code=code)
            except Language.DoesNotExist:
                self.stderr.write(f'Language "{code}" not in DB — run seed_language_exercises first.')
                continue

            exercises = LanguageExercise.objects.filter(
                topic_level__topic__language=language,
                exercise_type=LanguageExercise.PHONICS_MCQ,
                is_active=True,
            )

            total = exercises.count()
            self.stdout.write(f'\n{language.name} ({code}) — {total} phonics exercises')

            generated = skipped = errors = 0

            for ex in exercises:
                if ex.audio_file and not force:
                    skipped += 1
                    continue

                try:
                    buf = io.BytesIO()
                    tts = gTTS(text=ex.prompt, lang=gtts_code, slow=True)
                    tts.write_to_fp(buf)
                    buf.seek(0)

                    filename = f'{code}_{ex.pk}_{ex.prompt}.mp3'
                    # Remove any characters that would break a filename
                    safe_name = ''.join(
                        c if (c.isalnum() or c in '-_.') else '_'
                        for c in filename
                    )

                    # Delete old file if regenerating
                    if ex.audio_file and force:
                        try:
                            ex.audio_file.delete(save=False)
                        except Exception:
                            pass

                    ex.audio_file.save(safe_name, ContentFile(buf.read()), save=True)
                    generated += 1
                    self.stdout.write(f'  OK [{ex.pk}] saved')

                except Exception as e:
                    errors += 1
                    self.stderr.write(f'  ✗ [{ex.pk}] {ex.prompt}: {e}')

            self.stdout.write(self.style.SUCCESS(
                f'  Done — generated: {generated}, skipped: {skipped}, errors: {errors}'
            ))

        self.stdout.write(self.style.SUCCESS('\nAudio generation complete.'))
