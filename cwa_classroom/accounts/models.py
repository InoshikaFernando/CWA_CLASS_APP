from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.display_name

    # Convenience constants
    ADMIN = 'admin'
    SENIOR_TEACHER = 'senior_teacher'
    TEACHER = 'teacher'
    JUNIOR_TEACHER = 'junior_teacher'
    STUDENT = 'student'
    INDIVIDUAL_STUDENT = 'individual_student'
    ACCOUNTANT = 'accountant'
    HEAD_OF_DEPARTMENT = 'head_of_department'


class CustomUser(AbstractUser):
    date_of_birth = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    package = models.ForeignKey(
        'billing.Package',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='subscribers',
    )
    roles = models.ManyToManyField(
        Role,
        through='UserRole',
        through_fields=('user', 'role'),
        related_name='users',
        blank=True,
    )

    # Role priority order for dashboard redirect
    ROLE_PRIORITY = [
        Role.ADMIN,
        Role.HEAD_OF_DEPARTMENT,
        Role.ACCOUNTANT,
        Role.SENIOR_TEACHER,
        Role.TEACHER,
        Role.JUNIOR_TEACHER,
        Role.INDIVIDUAL_STUDENT,
        Role.STUDENT,
    ]

    def has_role(self, role_name):
        return self.roles.filter(name=role_name, is_active=True).exists()

    @property
    def primary_role(self):
        user_role_names = set(self.roles.filter(is_active=True).values_list('name', flat=True))
        for role_name in self.ROLE_PRIORITY:
            if role_name in user_role_names:
                return role_name
        return None

    @property
    def is_student(self):
        return self.has_role(Role.STUDENT)

    @property
    def is_individual_student(self):
        return self.has_role(Role.INDIVIDUAL_STUDENT)

    @property
    def is_senior_teacher(self):
        return self.has_role(Role.SENIOR_TEACHER)

    @property
    def is_teacher(self):
        return self.has_role(Role.TEACHER)

    @property
    def is_junior_teacher(self):
        return self.has_role(Role.JUNIOR_TEACHER)

    @property
    def is_any_teacher(self):
        """Returns True if user has any teacher-level role."""
        return self.roles.filter(
            name__in=[Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER],
            is_active=True,
        ).exists()

    @property
    def is_head_of_department(self):
        return self.has_role(Role.HEAD_OF_DEPARTMENT)

    @property
    def is_accountant(self):
        return self.has_role(Role.ACCOUNTANT)

    @property
    def is_admin_user(self):
        return self.has_role(Role.ADMIN)

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        from django.utils import timezone
        today = timezone.localdate()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def __str__(self):
        return self.username


class UserRole(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_roles')
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        CustomUser,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='role_assignments_made',
    )

    class Meta:
        unique_together = ('user', 'role')

    def __str__(self):
        return f'{self.user.username} → {self.role.name}'
