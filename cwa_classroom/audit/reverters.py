"""
Revert registry for audit log actions.

Each reverter receives the AuditLog entry and undoes the action using data
stored in ``entry.detail``.  Reverters must be idempotent.
"""
from django.db import transaction


def _revert_class_student_removed(entry):
    from classroom.models import ClassStudent, Enrollment
    detail = entry.detail
    student_id = detail.get('student_id')
    class_id = detail.get('class_id')
    if not student_id or not class_id:
        raise ValueError('Missing student_id or class_id in audit detail')
    with transaction.atomic():
        cs = ClassStudent.objects.filter(classroom_id=class_id, student_id=student_id).first()
        if cs:
            cs.is_active = True
            cs.save(update_fields=['is_active'])
        else:
            ClassStudent.objects.create(classroom_id=class_id, student_id=student_id)
        Enrollment.objects.filter(classroom_id=class_id, student_id=student_id, status='removed').update(status='approved')


def _revert_student_removed(entry):
    # Restore a school-level removal: reactivate the SchoolStudent link and the
    # EXACT ClassStudent links this removal deactivated (recorded in detail).
    #
    # Invoices are intentionally untouched: this only flips is_active flags.
    # Existing invoices are left as-is and none are generated (invoicing is a
    # separate, explicit step). Restoring only the recorded class links also
    # prevents re-adding the student to classes they had already left, which
    # would otherwise cause them to be billed again on the next invoice run.
    from classroom.models import SchoolStudent, ClassStudent
    student_id = entry.detail.get('student_id')
    school_id = entry.school_id
    if not student_id or not school_id:
        raise ValueError('Missing student_id or school_id')
    class_student_ids = entry.detail.get('class_student_ids')
    with transaction.atomic():
        SchoolStudent.objects.filter(
            school_id=school_id, student_id=student_id,
        ).update(is_active=True)
        if class_student_ids:
            ClassStudent.objects.filter(id__in=class_student_ids).update(is_active=True)
        else:
            # Legacy logs (pre-id-capture): best-effort restore of inactive links.
            ClassStudent.objects.filter(
                classroom__school_id=school_id, student_id=student_id, is_active=False,
            ).update(is_active=True)


def _revert_student_restored(entry):
    from classroom.models import SchoolStudent, ClassStudent
    student_id = entry.detail.get('student_id')
    school_id = entry.school_id
    if not student_id or not school_id:
        raise ValueError('Missing student_id or school_id')
    with transaction.atomic():
        SchoolStudent.objects.filter(school_id=school_id, student_id=student_id).update(is_active=False)
        ClassStudent.objects.filter(classroom__school_id=school_id, student_id=student_id).update(is_active=False)


def _revert_teacher_removed(entry):
    from classroom.models import SchoolTeacher
    teacher_id = entry.detail.get('teacher_id')
    school_id = entry.school_id
    if not teacher_id or not school_id:
        raise ValueError('Missing teacher_id or school_id')
    SchoolTeacher.objects.filter(school_id=school_id, teacher_id=teacher_id).update(is_active=True)


def _revert_teacher_restored(entry):
    from classroom.models import SchoolTeacher
    teacher_id = entry.detail.get('teacher_id')
    school_id = entry.school_id
    if not teacher_id or not school_id:
        raise ValueError('Missing teacher_id or school_id')
    SchoolTeacher.objects.filter(school_id=school_id, teacher_id=teacher_id).update(is_active=False)


def _revert_class_teacher_removed(entry):
    from classroom.models import ClassTeacher
    teacher_id = entry.detail.get('teacher_id')
    class_id = entry.detail.get('class_id')
    if not teacher_id or not class_id:
        raise ValueError('Missing teacher_id or class_id')
    if not ClassTeacher.objects.filter(classroom_id=class_id, teacher_id=teacher_id).exists():
        ClassTeacher.objects.create(classroom_id=class_id, teacher_id=teacher_id)


def _revert_enrollment_approved(entry):
    from classroom.models import ClassStudent, Enrollment
    enrollment_id = entry.detail.get('enrollment_id')
    student_id = entry.detail.get('student_id')
    classroom_id = entry.detail.get('classroom_id')
    if not enrollment_id:
        raise ValueError('Missing enrollment_id')
    with transaction.atomic():
        Enrollment.objects.filter(id=enrollment_id).update(status='pending')
        if student_id and classroom_id:
            ClassStudent.objects.filter(classroom_id=classroom_id, student_id=student_id).delete()


def _revert_enrollment_rejected(entry):
    from classroom.models import Enrollment
    enrollment_id = entry.detail.get('enrollment_id')
    if not enrollment_id:
        raise ValueError('Missing enrollment_id')
    Enrollment.objects.filter(id=enrollment_id).update(status='pending')


def _revert_hod_class_deleted(entry):
    from classroom.models import ClassRoom
    class_id = entry.detail.get('class_id')
    if not class_id:
        raise ValueError('Missing class_id')
    ClassRoom.objects.filter(id=class_id).update(is_active=True)


def _revert_hod_class_restored(entry):
    from classroom.models import ClassRoom
    class_id = entry.detail.get('class_id')
    if not class_id:
        raise ValueError('Missing class_id')
    ClassRoom.objects.filter(id=class_id).update(is_active=False)


def _revert_student_fee_updated(entry):
    from classroom.models import ClassStudent
    from decimal import Decimal, InvalidOperation
    class_student_id = entry.detail.get('class_student_id')
    old_fee = entry.detail.get('old_fee')
    if not class_student_id:
        raise ValueError('Missing class_student_id')
    fee_value = None
    if old_fee is not None and old_fee != '':
        try:
            fee_value = Decimal(str(old_fee))
        except (InvalidOperation, TypeError, ValueError):
            fee_value = None
    ClassStudent.objects.filter(id=class_student_id).update(fee_override=fee_value)


def _revert_parent_student_unlinked(entry):
    # Unlinking is a soft-delete (ParentStudent.is_active=False); revert reactivates the link.
    from classroom.models import ParentStudent
    link_id = entry.detail.get('link_id')
    if not link_id:
        raise ValueError('Missing link_id')
    ParentStudent.objects.filter(id=link_id).update(is_active=True)


def _revert_subject_archived(entry):
    from classroom.models import Subject
    subject_id = entry.detail.get('subject_id')
    if not subject_id:
        raise ValueError('Missing subject_id')
    Subject.objects.filter(id=subject_id).update(is_active=True)


def _revert_subject_restored(entry):
    from classroom.models import Subject
    subject_id = entry.detail.get('subject_id')
    if not subject_id:
        raise ValueError('Missing subject_id')
    Subject.objects.filter(id=subject_id).update(is_active=False)


def _revert_user_blocked(entry):
    # Blocking sets is_blocked=True; revert unblocks.
    from django.contrib.auth import get_user_model
    user_id = entry.detail.get('user_id')
    if not user_id:
        raise ValueError('Missing user_id')
    get_user_model().objects.filter(id=user_id).update(is_blocked=False, block_type='')


def _revert_user_unblocked(entry):
    # Unblocking sets is_blocked=False; revert re-blocks.
    from django.contrib.auth import get_user_model
    user_id = entry.detail.get('user_id')
    if not user_id:
        raise ValueError('Missing user_id')
    get_user_model().objects.filter(id=user_id).update(is_blocked=True)


def _revert_department_toggled_active(entry):
    from classroom.models import Department
    dept_id = entry.detail.get('department_id')
    new_state = entry.detail.get('is_active')
    if dept_id is None:
        raise ValueError('Missing department_id')
    Department.objects.filter(id=dept_id).update(is_active=not new_state)


def _revert_school_toggled_active(entry):
    from classroom.models import School
    school_id = entry.detail.get('school_id') or entry.school_id
    new_state = entry.detail.get('is_active')
    if school_id is None:
        raise ValueError('Missing school_id')
    School.objects.filter(id=school_id).update(is_active=not new_state)


def _revert_billing_plan_toggled(entry):
    from billing.models import BillingPlan
    plan_id = entry.detail.get('plan_id')
    new_state = entry.detail.get('is_active')
    if plan_id is None:
        raise ValueError('Missing plan_id')
    BillingPlan.objects.filter(id=plan_id).update(is_active=not new_state)


def _revert_discount_code_toggled(entry):
    from billing.models import DiscountCode
    code_id = entry.detail.get('discount_id')
    new_state = entry.detail.get('is_active')
    if code_id is None:
        raise ValueError('Missing discount_id')
    DiscountCode.objects.filter(id=code_id).update(is_active=not new_state)


REVERTIBLE_ACTIONS = {
    'class_student_removed': (_revert_class_student_removed, 'Re-add student to class'),
    'student_removed': (_revert_student_removed, 'Restore student to school'),
    'student_restored': (_revert_student_restored, 'Re-remove student from school'),
    'teacher_removed': (_revert_teacher_removed, 'Restore teacher to school'),
    'teacher_restored': (_revert_teacher_restored, 'Re-remove teacher from school'),
    'class_teacher_removed': (_revert_class_teacher_removed, 'Re-add teacher to class'),
    'enrollment_approved': (_revert_enrollment_approved, 'Undo enrollment approval'),
    'enrollment_rejected': (_revert_enrollment_rejected, 'Undo enrollment rejection'),
    'hod_class_deleted': (_revert_hod_class_deleted, 'Restore deleted class'),
    'hod_class_restored': (_revert_hod_class_restored, 'Re-delete restored class'),
    'student_fee_updated': (_revert_student_fee_updated, 'Restore previous fee'),
    'parent_student_unlinked': (_revert_parent_student_unlinked, 'Re-link parent to student'),
    'subject_archived': (_revert_subject_archived, 'Restore archived subject'),
    'subject_restored': (_revert_subject_restored, 'Re-archive subject'),
    'user_blocked': (_revert_user_blocked, 'Unblock user'),
    'user_unblocked': (_revert_user_unblocked, 'Re-block user'),
    'department_toggled_active': (_revert_department_toggled_active, 'Toggle department back'),
    'school_toggled_active': (_revert_school_toggled_active, 'Toggle school back'),
    'billing_plan_toggled': (_revert_billing_plan_toggled, 'Toggle billing plan back'),
    'discount_code_toggled': (_revert_discount_code_toggled, 'Toggle discount code back'),
}

ACTION_LABELS = {
    'class_student_removed': 'Removed student from class',
    'student_removed': 'Removed student from school',
    'student_restored': 'Restored student to school',
    'student_added': 'Added student to school',
    'student_edited': 'Edited student details',
    'student_enrolled': 'Enrolled student in class',
    'student_classes_updated': 'Updated student class assignments',
    'student_batch_updated': 'Batch updated students',
    'student_fee_updated': 'Updated student fee',
    'teacher_removed': 'Removed teacher from school',
    'teacher_restored': 'Restored teacher to school',
    'teacher_added': 'Added teacher to school',
    'teacher_edited': 'Edited teacher details',
    'teacher_batch_updated': 'Batch updated teachers',
    'class_teacher_removed': 'Removed teacher from class',
    'teachers_updated': 'Updated class teachers',
    'enrollment_approved': 'Approved enrollment request',
    'enrollment_rejected': 'Rejected enrollment request',
    'class_created': 'Created class',
    'class_edited': 'Edited class',
    'hod_class_created': 'Created class',
    'hod_class_deleted': 'Deleted class',
    'hod_class_restored': 'Restored class',
    'hod_class_assigned': 'Assigned class to department',
    'session_created': 'Created session',
    'session_started': 'Started session',
    'session_completed': 'Completed session',
    'session_cancelled': 'Cancelled session',
    'session_deleted': 'Deleted session',
    'sessions_rescheduled': 'Rescheduled sessions',
    'attendance_marked': 'Marked attendance',
    'session_attendance_saved': 'Saved session attendance',
    'student_attendance_approved': 'Approved student attendance',
    'student_attendance_rejected': 'Rejected student attendance',
    'student_attendance_bulk_approved': 'Bulk approved attendance',
    'teacher_self_attendance_recorded': 'Recorded own attendance',
    'attendance_session_created': 'Created attendance session',
    'attendance_session_deleted': 'Deleted attendance session',
    'absence_token_approved': 'Approved absence token',
    'absence_token_rejected': 'Rejected absence token',
    'parent_student_unlinked': 'Unlinked parent from student',
    'parent_invited': 'Invited parent',
    'parent_invite_revoked': 'Revoked parent invite',
    'parent_link_approved': 'Approved parent link',
    'parent_link_rejected': 'Rejected parent link',
    'parent_link_edited': 'Edited parent link',
    'parent_linked_existing': 'Linked existing parent',
    'parent_created_direct': 'Created parent directly',
    'guardian_edited': 'Edited guardian details',
    'school_created': 'Created school',
    'school_edited': 'Edited school',
    'school_toggled_active': 'Toggled school active status',
    'school_deleted': 'Deleted school',
    'school_settings_updated': 'Updated school settings',
    'school_suspended': 'Suspended school',
    'school_unsuspended': 'Unsuspended school',
    'staff_roles_updated': 'Updated staff roles',
    'department_created': 'Created department',
    'department_edited': 'Edited department',
    'department_toggled_active': 'Toggled department active status',
    'department_deleted': 'Deleted department',
    'department_hod_assigned': 'Assigned HoD to department',
    'department_teachers_updated': 'Updated department teachers',
    'department_classes_assigned': 'Assigned classes to department',
    'department_levels_updated': 'Updated department levels',
    'department_level_created': 'Created department level',
    'department_level_removed': 'Removed department level',
    'department_level_edited': 'Edited department level',
    'department_subject_added': 'Added subject to department',
    'department_subject_edited': 'Edited department subject',
    'department_subject_moved': 'Moved department subject',
    'department_subject_fee_updated': 'Updated department subject fee',
    'department_fee_updated': 'Updated department fee',
    'subject_created': 'Created subject',
    'subject_edited': 'Edited subject',
    'subject_archived': 'Archived subject',
    'subject_restored': 'Restored subject',
    'subject_added_to_department': 'Added subject to department',
    'subject_moved': 'Moved subject',
    'subject_fee_edited': 'Edited subject fee',
    'level_created': 'Created level',
    'level_edited': 'Edited level',
    'level_removed': 'Removed level',
    'academic_year_created': 'Created academic year',
    'academic_year_updated': 'Updated academic year',
    'term_created': 'Created term',
    'term_edited': 'Edited term',
    'term_deleted': 'Deleted term',
    'term_confirmed': 'Confirmed term',
    'term_force_confirmed': 'Force confirmed term',
    'terms_setup': 'Set up terms',
    'holiday_created': 'Created holiday',
    'holiday_edited': 'Edited holiday',
    'holiday_deleted': 'Deleted holiday',
    'user_blocked': 'Blocked user',
    'user_unblocked': 'Unblocked user',
    'questions_uploaded': 'Uploaded questions',
    'question_created': 'Created question',
    'question_edited': 'Edited question',
    'question_deleted': 'Deleted question',
    'billing_plan_toggled': 'Toggled billing plan',
    'discount_code_toggled': 'Toggled discount code',
    'action_reverted': 'Reverted an action',
    'school_switched': 'Switched school',
}
