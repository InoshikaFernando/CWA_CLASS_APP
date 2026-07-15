from datetime import timedelta
from io import StringIO
from django.core.management import call_command
from django.utils import timezone
from maths.models import Question
from .models import Homework, HomeworkQuestion
from .tests import HomeworkTestBase


class FindDanglingCmdTest(HomeworkTestBase):
    def test_reports_dangling_item(self):
        hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher, title='Dangler',
            homework_type='topic', num_questions=1,
            due_date=timezone.now() + timedelta(days=7))
        q = Question.objects.create(
            level=self.level, question_text='temp',
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1)
        HomeworkQuestion.objects.create(
            homework=hw, subject_slug='mathematics', content_id=q.id, order=0)
        Question.objects.filter(id=q.id).delete()

        out = StringIO()
        call_command('find_dangling_homework_items', '--homework', str(hw.id), stdout=out)
        text = out.getvalue()
        self.assertIn('dangling', text.lower())
        self.assertIn(f'homework #{hw.id}', text)
        self.assertIn(f'content_id={q.id}', text)
