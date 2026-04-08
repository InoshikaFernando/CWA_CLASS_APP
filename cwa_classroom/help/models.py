from django.db import models


ROLE_GROUP_CHOICES = [
    ('hoi', 'Head of Institute / Owner'),
    ('hod', 'Head of Department'),
    ('teacher', 'Teachers (all levels)'),
    ('accountant', 'Accountant'),
    ('parent', 'Parent'),
    ('student', 'Student'),
    ('admin', 'Admin'),
]

MODULE_CHOICES = [
    ('', '(No specific module)'),
    ('classroom', 'Classroom / Classes'),
    ('billing', 'Billing & Payments'),
    ('attendance', 'Attendance'),
    ('progress', 'Progress & Reports'),
    ('quiz', 'Quizzes & Questions'),
    ('maths', 'Maths'),
    ('coding', 'Coding'),
    ('music', 'Music'),
    ('science', 'Science'),
    ('number_puzzles', 'Number Puzzles'),
    ('ai_import', 'AI Import'),
    ('audit', 'Audit'),
    ('accounts', 'Account & Profile'),
    ('hierarchy', 'School Hierarchy'),
    ('invoicing', 'Invoicing'),
    ('salaries', 'Salaries'),
]


class HelpCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon_svg = models.TextField(blank=True, help_text='Optional inline SVG markup for the category icon')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Help Category'
        verbose_name_plural = 'Help Categories'

    def __str__(self):
        return self.name


class HelpArticleManager(models.Manager):
    def for_role_group(self, role_group):
        return self.filter(
            is_published=True,
            article_roles__role_group=role_group,
        ).select_related('category').distinct()

    def for_page(self, role_group, url_name):
        return self.for_role_group(role_group).filter(page_url_name=url_name)

    def for_module(self, role_group, module):
        return self.for_role_group(role_group).filter(module=module)


class HelpArticle(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    category = models.ForeignKey(HelpCategory, on_delete=models.CASCADE, related_name='articles')
    body_markdown = models.TextField()
    excerpt = models.CharField(max_length=300, blank=True)
    module = models.CharField(max_length=100, blank=True, choices=MODULE_CHOICES)
    page_url_name = models.CharField(
        max_length=150,
        blank=True,
        help_text='Django URL name for context-sensitive help (e.g. teacher_dashboard, enrollment_requests). Leave blank for module-level articles.',
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False, help_text='Pin to top of help centre')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = HelpArticleManager()

    class Meta:
        ordering = ['category__order', 'order', 'title']
        indexes = [
            models.Index(fields=['module']),
            models.Index(fields=['page_url_name']),
            models.Index(fields=['is_published']),
        ]

    def __str__(self):
        return self.title

    @property
    def body_html(self):
        if not hasattr(self, '_body_html'):
            import markdown
            self._body_html = markdown.markdown(
                self.body_markdown,
                extensions=['fenced_code', 'tables', 'toc', 'nl2br'],
            )
        return self._body_html


class HelpArticleRole(models.Model):
    article = models.ForeignKey(HelpArticle, on_delete=models.CASCADE, related_name='article_roles')
    role_group = models.CharField(max_length=30, choices=ROLE_GROUP_CHOICES)

    class Meta:
        unique_together = ('article', 'role_group')
        verbose_name = 'Article Role'
        verbose_name_plural = 'Article Roles'

    def __str__(self):
        return f'{self.article.title} — {self.get_role_group_display()}'


class FAQ(models.Model):
    question = models.CharField(max_length=300)
    answer_markdown = models.TextField()
    role_group = models.CharField(max_length=30, choices=ROLE_GROUP_CHOICES)
    category = models.ForeignKey(
        HelpCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='faqs'
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'question']
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQs'

    def __str__(self):
        return self.question

    @property
    def answer_html(self):
        if not hasattr(self, '_answer_html'):
            import markdown
            self._answer_html = markdown.markdown(
                self.answer_markdown,
                extensions=['nl2br'],
            )
        return self._answer_html
