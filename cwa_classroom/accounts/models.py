from django.conf import settings
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
    HEAD_OF_INSTITUTE = 'head_of_institute'
    HEAD_OF_DEPARTMENT = 'head_of_department'
    INSTITUTE_OWNER = 'institute_owner'
    PARENT = 'parent'


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

    # Address / contact
    phone = models.CharField(max_length=30, blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    # Profile completion
    must_change_password = models.BooleanField(default=False)
    profile_completed = models.BooleanField(default=True)

    # Account blocking
    BLOCK_TEMPORARY = 'temporary'
    BLOCK_PERMANENT = 'permanent'
    BLOCK_TYPE_CHOICES = [
        (BLOCK_TEMPORARY, 'Temporary'),
        (BLOCK_PERMANENT, 'Permanent'),
    ]

    is_blocked = models.BooleanField(default=False)
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.TextField(blank=True)
    blocked_by = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='blocked_users',
    )
    block_type = models.CharField(
        max_length=20, choices=BLOCK_TYPE_CHOICES, blank=True,
    )
    block_expires_at = models.DateTimeField(null=True, blank=True)

    # Role priority order for dashboard redirect
    ROLE_PRIORITY = [
        Role.ADMIN,
        Role.INSTITUTE_OWNER,
        Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
        Role.ACCOUNTANT,
        Role.SENIOR_TEACHER,
        Role.TEACHER,
        Role.JUNIOR_TEACHER,
        Role.INDIVIDUAL_STUDENT,
        Role.STUDENT,
        Role.PARENT,
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
    def is_head_of_institute(self):
        return self.has_role(Role.HEAD_OF_INSTITUTE)

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
    def is_institute_owner(self):
        return self.has_role(Role.INSTITUTE_OWNER)

    @property
    def is_parent(self):
        return self.has_role(Role.PARENT)

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
