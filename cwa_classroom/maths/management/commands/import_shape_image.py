"""Create a shape_select question from an uploaded shapes image.

Detects the shapes in an image (OpenCV, with optional Claude-vision fallback),
builds a validated shape_spec, and creates a ``shape_select`` Question. The
detection engine traces outlines to SVG, so no raster image is stored.

    python manage.py import_shape_image --image sheet.png --target triangle --level 4

``--no-ai`` keeps it strictly token-free (OpenCV only). The AI fallback only
runs when OpenCV finds no shape of the target type AND ``--no-ai`` is absent.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create a shape_select question from an image of shapes.'

    def add_arguments(self, parser):
        parser.add_argument('--image', required=True, help='Path to the image file.')
        parser.add_argument('--target', required=True, help='Target shape type, e.g. triangle.')
        parser.add_argument('--level', type=int, required=True, help='Level (year) number.')
        parser.add_argument('--topic', default='', help='Optional topic name to attach.')
        parser.add_argument('--text', default='', help='Question text (defaults to "Colour all the <target>s.").')
        parser.add_argument('--no-ai', action='store_true', help='OpenCV only — never call the AI fallback.')

    def handle(self, *args, **opts):
        from classroom.models import Level, Topic
        from maths.models import Question
        from maths.shape_detect import build_shape_spec_from_image

        path = Path(opts['image'])
        if not path.exists():
            raise CommandError(f'Image not found: {path}')

        level = Level.objects.filter(level_number=opts['level']).first()
        if level is None:
            raise CommandError(f'No Level with level_number={opts["level"]}.')

        media_type = 'image/jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
        try:
            spec, backend = build_shape_spec_from_image(
                path.read_bytes(), opts['target'],
                allow_ai=not opts['no_ai'], media_type=media_type,
            )
        except ValueError as exc:
            raise CommandError(f'Detection failed: {exc}')

        target = opts['target']
        text = opts['text'] or f'Colour all the {target}s.'
        topic = None
        if opts['topic']:
            topic = Topic.objects.filter(name=opts['topic']).first()
            if topic is None:
                raise CommandError(f'No topic named {opts["topic"]!r}.')

        question = Question.objects.create(
            level=level, topic=topic, question_text=text,
            question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
            shape_spec=spec,
        )
        n_target = sum(1 for s in spec['shapes'] if s['type'] == target)
        self.stdout.write(self.style.SUCCESS(
            f'Created shape_select question #{question.pk} via {backend}: '
            f'{len(spec["shapes"])} shapes, {n_target} {target}(s).'
        ))
