"""Row-level scoping: turn "who is asking" into "which rows they may read".

Every list endpoint in the API narrows its queryset through one of these
helpers. They are written once, here, because the alternative — each viewset
filtering by hand — is how one forgotten ``.filter()`` turns into a roster of
another school's children.

The rules, in the order they are checked:

* superuser            → everything
* student              → their own rows only
* parent               → the rows of children linked via ``ParentStudent``
* teacher              → the students in classes they teach
* institute staff      → the students in schools they own or run

Note that these are *visibility* rules only. Whether a role may WRITE is a
separate question, answered by the permission classes in ``api.permissions``.
"""

from django.db.models import Q

from classroom.models import ClassRoom, ClassStudent, ParentStudent, School, SchoolTeacher


def schools_administered_by(user):
    """Schools *user* owns or is institute staff at."""
    if not user.is_authenticated:
        return School.objects.none()
    if user.is_superuser:
        return School.objects.all()
    owned = School.objects.filter(admin=user)
    staffed = School.objects.filter(
        id__in=SchoolTeacher.objects.filter(
            teacher=user, is_active=True,
            role__in=['head_of_institute', 'head_of_department'],
        ).values_list('school_id', flat=True)
    )
    return (owned | staffed).distinct()


def classrooms_for(user):
    """Classes *user* may see: taught, enrolled in, a child's, or administered."""
    if not user.is_authenticated:
        return ClassRoom.objects.none()
    if user.is_superuser:
        return ClassRoom.objects.all()

    condition = Q(class_teachers__teacher=user, is_active=True)
    condition |= Q(class_students__student=user, class_students__is_active=True)

    child_ids = list(child_ids_of(user))
    if child_ids:
        condition |= Q(class_students__student_id__in=child_ids,
                       class_students__is_active=True)

    administered = schools_administered_by(user)
    if administered.exists():
        condition |= Q(school__in=administered)

    return ClassRoom.objects.filter(condition).distinct()


def child_ids_of(user):
    """IDs of the students a parent is linked to. Empty for everyone else."""
    if not user.is_authenticated or not user.is_parent:
        return ParentStudent.objects.none().values_list('student_id', flat=True)
    return (ParentStudent.objects
            .filter(parent=user, is_active=True)
            .values_list('student_id', flat=True))


def visible_student_ids(user):
    """Every student id *user* may read data for.

    Returns a set rather than a queryset: callers use it inside ``__in``
    lookups that are evaluated repeatedly, and the membership is small (a
    family, a class, a school) in every case but superuser — which short
    -circuits before building one.
    """
    if not user.is_authenticated:
        return set()

    ids = set()
    if user.is_student or user.is_individual_student:
        ids.add(user.id)

    ids.update(child_ids_of(user))

    taught = ClassStudent.objects.filter(
        classroom__class_teachers__teacher=user,
        classroom__is_active=True,
        is_active=True,
    ).values_list('student_id', flat=True)
    ids.update(taught)

    administered = schools_administered_by(user)
    if administered.exists():
        ids.update(
            ClassStudent.objects
            .filter(classroom__school__in=administered, is_active=True)
            .values_list('student_id', flat=True)
        )

    return ids


def scope_by_student(queryset, user, field='student'):
    """Narrow *queryset* to rows whose ``field`` is a student *user* may read.

    The superuser short-circuit is deliberate: building the full id set for an
    admin on a large instance is a pointless table scan.
    """
    if not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset
    return queryset.filter(**{f'{field}_id__in': visible_student_ids(user)})
