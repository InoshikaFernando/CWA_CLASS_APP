"""
Student CSV bulk import — parsing, validation, preview, and execution.
"""
import csv
import io
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from accounts.models import CustomUser, Role, UserRole
from .models import (
    School, SchoolStudent, Department, DepartmentSubject,
    Subject, Level, ClassRoom, ClassStudent,
    Guardian, StudentGuardian,
)

logger = logging.getLogger(__name__)

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_CSV_ROWS = 5000

# All mappable columns — key is the system field, value is the display label
COLUMN_FIELDS = {
    # Required
    'first_name': 'First Name',
    'last_name': 'Last Name',
    'email': 'Student Email',
    # Optional — student
    'username': 'Username',
    'date_of_birth': 'Date of Birth',
    'country': 'Country',
    'region': 'Region',
    'opening_balance': 'Opening Balance',
    # Optional — class structure
    'department': 'Department',
    'subject': 'Subject',
    'level': 'Level',
    'class_name': 'Class Name',
    'class_day': 'Class Day',
    'class_start_time': 'Class Start Time',
    'class_end_time': 'Class End Time',
    # Optional — parent 1
    'parent1_first_name': 'Parent 1 First Name',
    'parent1_last_name': 'Parent 1 Last Name',
    'parent1_email': 'Parent 1 Email',
    'parent1_phone': 'Parent 1 Phone',
    'parent1_relationship': 'Parent 1 Relationship',
    'parent1_address': 'Parent 1 Address',
    'parent1_city': 'Parent 1 City',
    'parent1_country': 'Parent 1 Country',
    # Optional — parent 2
    'parent2_first_name': 'Parent 2 First Name',
    'parent2_last_name': 'Parent 2 Last Name',
    'parent2_email': 'Parent 2 Email',
    'parent2_phone': 'Parent 2 Phone',
    'parent2_relationship': 'Parent 2 Relationship',
    'parent2_address': 'Parent 2 Address',
    'parent2_city': 'Parent 2 City',
    'parent2_country': 'Parent 2 Country',
}

REQUIRED_FIELDS = {'first_name', 'last_name', 'email'}

# ── Source system presets ────────────────────────────────────
# Each preset maps our system field → the CSV/XLS header name used by that system.
# To add a new source system, add an entry here — no code changes needed.

SOURCE_PRESETS = {
    'teachworks': {
        'name': 'Teachworks',
        'description': 'Import from Teachworks Students export (.xls or .csv)',
        'file_type': 'Students',
        'mapping': {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email',
            'date_of_birth': 'Birth Date',
            'level': 'Subjects',
            'class_name': 'Default Service',
            'parent1_first_name': 'Family First',
            'parent1_last_name': 'Family Last',
            'parent1_email': 'Family Email',
            'parent1_phone': 'Family phone',
            'parent1_address': 'Address',
            'parent1_city': 'City',
            'parent1_country': 'Country',
        },
    },
    # Add more presets here as needed, e.g.:
    # 'hero': {
    #     'name': 'HERO',
    #     'description': 'Import from HERO student export',
    #     'mapping': { ... },
    # },
}


def apply_preset(preset_key, headers):
    """Apply a source preset to auto-map column indices from CSV headers.

    Returns a column_mapping dict {system_field: column_index} ready for
    validate_and_preview().
    """
    preset = SOURCE_PRESETS.get(preset_key)
    if not preset:
        return {}

    # Build a case-insensitive header lookup
    header_lower = {h.lower().strip(): i for i, h in enumerate(headers)}

    mapping = {}
    for system_field, csv_header in preset['mapping'].items():
        idx = header_lower.get(csv_header.lower())
        if idx is not None:
            mapping[system_field] = idx
    return mapping


DAY_MAP = {
    'monday': 'monday', 'mon': 'monday',
    'tuesday': 'tuesday', 'tue': 'tuesday', 'tues': 'tuesday',
    'wednesday': 'wednesday', 'wed': 'wednesday',
    'thursday': 'thursday', 'thu': 'thursday', 'thur': 'thursday', 'thurs': 'thursday',
    'friday': 'friday', 'fri': 'friday',
    'saturday': 'saturday', 'sat': 'saturday',
    'sunday': 'sunday', 'sun': 'sunday',
}

RELATIONSHIP_MAP = {
    'mother': 'mother', 'mom': 'mother', 'mum': 'mother',
    'father': 'father', 'dad': 'father',
    'guardian': 'guardian',
    'other': 'other',
}


def parse_csv_file(file_content):
    """Parse CSV content bytes. Returns (headers, data_rows) or raises ValueError."""
    try:
        content = file_content.decode('utf-8')
    except UnicodeDecodeError:
        content = file_content.decode('latin-1')

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    if len(rows) < 2:
        raise ValueError('CSV must have a header row and at least one data row.')
    if len(rows) - 1 > MAX_CSV_ROWS:
        raise ValueError(f'CSV exceeds maximum of {MAX_CSV_ROWS} rows.')

    headers = [h.strip() for h in rows[0]]
    data_rows = rows[1:]
    return headers, data_rows


def parse_xls_file(file_content):
    """Parse .xls file bytes. Returns (headers, data_rows) or raises ValueError."""
    try:
        import xlrd
    except ImportError:
        raise ValueError('XLS support requires the xlrd package. Install with: pip install xlrd')

    wb = xlrd.open_workbook(file_contents=file_content)
    sh = wb.sheet_by_index(0)

    if sh.nrows < 2:
        raise ValueError('XLS must have a header row and at least one data row.')
    if sh.nrows - 1 > MAX_CSV_ROWS:
        raise ValueError(f'XLS exceeds maximum of {MAX_CSV_ROWS} rows.')

    headers = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]

    data_rows = []
    for r in range(1, sh.nrows):
        row = []
        for c in range(sh.ncols):
            cell = sh.cell(r, c)
            if cell.ctype == xlrd.XL_CELL_DATE:
                # Convert Excel date serial to date string
                try:
                    dt = xlrd.xldate_as_datetime(cell.value, wb.datemode)
                    row.append(dt.strftime('%Y-%m-%d'))
                except Exception:
                    row.append(str(cell.value))
            elif cell.ctype == xlrd.XL_CELL_NUMBER:
                # Keep as int if whole number, else float string
                if cell.value == int(cell.value):
                    row.append(str(int(cell.value)))
                else:
                    row.append(str(cell.value))
            else:
                row.append(str(cell.value).strip())
        data_rows.append(row)

    return headers, data_rows


def parse_upload_file(file_content, filename):
    """Route to CSV or XLS parser based on file extension."""
    ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if ext == 'xls':
        return parse_xls_file(file_content)
    elif ext == 'xlsx':
        raise ValueError('XLSX format is not supported. Please save as .xls or export as .csv.')
    else:
        return parse_csv_file(file_content)


def _get_cell(row, col_idx):
    """Safely get a cell value by column index, return stripped string or ''."""
    if col_idx is None or col_idx < 0 or col_idx >= len(row):
        return ''
    return row[col_idx].strip()


def _parse_date(val):
    """Try to parse a date string in common formats."""
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(val):
    """Parse HH:MM time string."""
    for fmt in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p'):
        try:
            return datetime.strptime(val, fmt).time()
        except ValueError:
            continue
    return None


def _build_column_mapping(post_data):
    """Build column_mapping dict from POST data. Maps field_name -> column_index."""
    mapping = {}
    for field in COLUMN_FIELDS:
        val = post_data.get(f'col_{field}', '')
        if val != '' and val != '-1':
            mapping[field] = int(val)
    return mapping


def validate_and_preview(data_rows, column_mapping, school):
    """
    Process CSV rows into a preview of what will be created.
    Returns dict with categorised results.
    """
    errors = []
    warnings = []

    # Check required fields are mapped
    for f in REQUIRED_FIELDS:
        if f not in column_mapping:
            errors.append(f'Required column "{COLUMN_FIELDS[f]}" is not mapped.')
    if errors:
        return {'errors': errors, 'warnings': warnings}

    # Collect student data grouped by email
    students_by_email = {}
    for row_idx, row in enumerate(data_rows, start=2):  # row 2 = first data row
        email = _get_cell(row, column_mapping.get('email')).lower()
        if not email:
            errors.append(f'Row {row_idx}: Missing email.')
            continue
        first_name = _get_cell(row, column_mapping.get('first_name'))
        last_name = _get_cell(row, column_mapping.get('last_name'))
        if not first_name or not last_name:
            errors.append(f'Row {row_idx}: Missing first or last name.')
            continue

        if email not in students_by_email:
            username = _get_cell(row, column_mapping.get('username'))
            if not username:
                username = email.split('@')[0]
            dob_str = _get_cell(row, column_mapping.get('date_of_birth'))
            dob = _parse_date(dob_str) if dob_str else None
            if dob_str and not dob:
                warnings.append(f'Row {row_idx}: Could not parse date "{dob_str}".')
            balance_str = _get_cell(row, column_mapping.get('opening_balance'))
            try:
                opening_balance = Decimal(balance_str) if balance_str else Decimal('0')
            except InvalidOperation:
                opening_balance = Decimal('0')
                warnings.append(f'Row {row_idx}: Invalid opening_balance "{balance_str}".')

            students_by_email[email] = {
                'email': email,
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'date_of_birth': dob,
                'country': _get_cell(row, column_mapping.get('country')),
                'region': _get_cell(row, column_mapping.get('region')),
                'opening_balance': opening_balance,
                'classes': [],
                'guardians': [],
                'row_indices': [],
            }

        student = students_by_email[email]
        student['row_indices'].append(row_idx)

        # Collect class assignment from this row
        class_name = _get_cell(row, column_mapping.get('class_name'))
        if class_name:
            day_raw = _get_cell(row, column_mapping.get('class_day')).lower()
            student['classes'].append({
                'class_name': class_name,
                'department': _get_cell(row, column_mapping.get('department')),
                'subject': _get_cell(row, column_mapping.get('subject')),
                'level': _get_cell(row, column_mapping.get('level')),
                'day': DAY_MAP.get(day_raw, ''),
                'start_time': _parse_time(_get_cell(row, column_mapping.get('class_start_time'))),
                'end_time': _parse_time(_get_cell(row, column_mapping.get('class_end_time'))),
            })

        # Collect guardian data from this row
        for prefix in ('parent1', 'parent2'):
            g_email = _get_cell(row, column_mapping.get(f'{prefix}_email')).lower()
            g_first = _get_cell(row, column_mapping.get(f'{prefix}_first_name'))
            if g_email and g_first:
                rel_raw = _get_cell(row, column_mapping.get(f'{prefix}_relationship')).lower()
                guardian_data = {
                    'email': g_email,
                    'first_name': g_first,
                    'last_name': _get_cell(row, column_mapping.get(f'{prefix}_last_name')),
                    'phone': _get_cell(row, column_mapping.get(f'{prefix}_phone')),
                    'relationship': RELATIONSHIP_MAP.get(rel_raw, 'guardian'),
                    'address': _get_cell(row, column_mapping.get(f'{prefix}_address')),
                    'city': _get_cell(row, column_mapping.get(f'{prefix}_city')),
                    'country': _get_cell(row, column_mapping.get(f'{prefix}_country')),
                    'is_primary': prefix == 'parent1',
                }
                # Deduplicate within this student's guardian list
                if not any(g['email'] == g_email for g in student['guardians']):
                    student['guardians'].append(guardian_data)

    # Categorise entities as new or existing
    existing_emails = set(
        CustomUser.objects.filter(
            email__in=students_by_email.keys()
        ).values_list('email', flat=True)
    )

    students_new = []
    students_existing = []
    for email, sdata in students_by_email.items():
        if email in existing_emails:
            students_existing.append(sdata)
        else:
            students_new.append(sdata)

    # Collect unique class structures
    all_classes = {}
    for sdata in students_by_email.values():
        for c in sdata['classes']:
            key = (c['class_name'], c['department'], c['subject'])
            if key not in all_classes:
                all_classes[key] = c

    existing_class_names = set(
        ClassRoom.objects.filter(
            school=school, name__in=[c['class_name'] for c in all_classes.values()]
        ).values_list('name', flat=True)
    )
    classes_new = [c for c in all_classes.values() if c['class_name'] not in existing_class_names]
    classes_existing = [c for c in all_classes.values() if c['class_name'] in existing_class_names]

    # Unique departments to create
    existing_dept_names = set(
        Department.objects.filter(school=school).values_list('name', flat=True)
    )
    dept_names_in_csv = {c['department'] for c in all_classes.values() if c['department']}
    departments_new = [d for d in dept_names_in_csv if d not in existing_dept_names]

    # Unique subjects
    existing_subject_slugs = set(
        Subject.objects.filter(
            models.Q(school=school) | models.Q(school__isnull=True)
        ).values_list('slug', flat=True)
    )
    subject_names_in_csv = {c['subject'] for c in all_classes.values() if c['subject']}
    subjects_new = [s for s in subject_names_in_csv if slugify(s) not in existing_subject_slugs]

    # Unique guardians
    all_guardians = {}
    for sdata in students_by_email.values():
        for g in sdata['guardians']:
            all_guardians[g['email']] = g
    existing_guardian_emails = set(
        Guardian.objects.filter(
            school=school, email__in=all_guardians.keys()
        ).values_list('email', flat=True)
    )
    guardians_new = [g for g in all_guardians.values() if g['email'] not in existing_guardian_emails]
    guardians_existing = [g for g in all_guardians.values() if g['email'] in existing_guardian_emails]

    return {
        'students_new': students_new,
        'students_existing': students_existing,
        'departments_new': departments_new,
        'subjects_new': subjects_new,
        'classes_new': classes_new,
        'classes_existing': classes_existing,
        'guardians_new': guardians_new,
        'guardians_existing': guardians_existing,
        'errors': errors,
        'warnings': warnings,
    }


def execute_import(preview_data, school, uploaded_by):
    """
    Execute the import in a single transaction.
    Returns dict with counts and credentials list.
    """
    from django.db import models as db_models

    credentials = []
    counts = {
        'students_created': 0,
        'students_enrolled': 0,
        'classes_created': 0,
        'departments_created': 0,
        'subjects_created': 0,
        'guardians_created': 0,
        'errors': [],
    }

    role_student, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={'display_name': 'Student'},
    )

    with transaction.atomic():
        # 1. Create departments
        dept_cache = {}
        for dept_name in preview_data['departments_new']:
            dept, created = Department.objects.get_or_create(
                school=school, slug=slugify(dept_name),
                defaults={'name': dept_name},
            )
            dept_cache[dept_name] = dept
            if created:
                counts['departments_created'] += 1
        # Also cache existing departments
        for dept in Department.objects.filter(school=school):
            dept_cache[dept.name] = dept

        # 2. Create subjects
        subject_cache = {}
        for subj_name in preview_data['subjects_new']:
            subj, created = Subject.objects.get_or_create(
                school=school, slug=slugify(subj_name),
                defaults={'name': subj_name, 'is_active': True},
            )
            subject_cache[subj_name] = subj
            if created:
                counts['subjects_created'] += 1
        # Cache existing subjects (school + global)
        for subj in Subject.objects.filter(
            db_models.Q(school=school) | db_models.Q(school__isnull=True)
        ):
            subject_cache[subj.name] = subj

        # Link new subjects to departments via DepartmentSubject
        for cls_data in preview_data['classes_new'] + preview_data['classes_existing']:
            dept_name = cls_data.get('department', '')
            subj_name = cls_data.get('subject', '')
            if dept_name and subj_name and dept_name in dept_cache and subj_name in subject_cache:
                DepartmentSubject.objects.get_or_create(
                    department=dept_cache[dept_name],
                    subject=subject_cache[subj_name],
                )

        # 3. Resolve levels (match by display_name or level_number)
        level_cache = {}
        for lvl in Level.objects.all():
            level_cache[lvl.display_name.lower()] = lvl
            level_cache[str(lvl.level_number)] = lvl
            if lvl.display_name:
                level_cache[lvl.display_name.lower()] = lvl

        # 4. Create classes
        class_cache = {}
        for cls_data in preview_data['classes_new']:
            dept = dept_cache.get(cls_data.get('department', ''))
            subj = subject_cache.get(cls_data.get('subject', ''))
            classroom = ClassRoom.objects.create(
                name=cls_data['class_name'],
                school=school,
                department=dept,
                subject=subj,
                day=cls_data.get('day', ''),
                start_time=cls_data.get('start_time'),
                end_time=cls_data.get('end_time'),
                created_by=uploaded_by,
            )
            # Link level if present
            level_key = cls_data.get('level', '').lower()
            if level_key and level_key in level_cache:
                classroom.levels.add(level_cache[level_key])
            class_cache[cls_data['class_name']] = classroom
            counts['classes_created'] += 1
        # Cache existing classes
        for cr in ClassRoom.objects.filter(school=school):
            class_cache[cr.name] = cr

        # 5. Create guardians
        guardian_cache = {}
        for g_data in preview_data['guardians_new']:
            guardian, created = Guardian.objects.get_or_create(
                school=school, email=g_data['email'],
                defaults={
                    'first_name': g_data['first_name'],
                    'last_name': g_data['last_name'],
                    'phone': g_data.get('phone', ''),
                    'relationship': g_data.get('relationship', 'guardian'),
                    'address': g_data.get('address', ''),
                    'city': g_data.get('city', ''),
                    'country': g_data.get('country', ''),
                },
            )
            guardian_cache[g_data['email']] = guardian
            if created:
                counts['guardians_created'] += 1
        # Cache existing guardians
        for g in Guardian.objects.filter(school=school):
            guardian_cache[g.email] = g

        # 6-9. Create students, enroll, link guardians
        all_students = preview_data['students_new'] + preview_data['students_existing']
        for sdata in all_students:
            email = sdata['email']
            is_new = not CustomUser.objects.filter(email=email).exists()

            if is_new:
                password = get_random_string(10)
                # Ensure unique username
                base_username = sdata['username']
                username = base_username
                suffix = 1
                while CustomUser.objects.filter(username=username).exists():
                    username = f'{base_username}{suffix}'
                    suffix += 1

                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=sdata['first_name'],
                    last_name=sdata['last_name'],
                )
                if sdata.get('date_of_birth'):
                    user.date_of_birth = sdata['date_of_birth']
                if sdata.get('country'):
                    user.country = sdata['country']
                if sdata.get('region'):
                    user.region = sdata['region']
                user.save()
                UserRole.objects.get_or_create(user=user, role=role_student)
                credentials.append({
                    'username': username,
                    'email': email,
                    'password': password,
                    'first_name': sdata['first_name'],
                    'last_name': sdata['last_name'],
                })
                counts['students_created'] += 1
            else:
                user = CustomUser.objects.get(email=email)
                password = None

            # SchoolStudent
            SchoolStudent.objects.get_or_create(
                school=school, student=user,
                defaults={'opening_balance': sdata.get('opening_balance', Decimal('0'))},
            )

            # ClassStudent enrollments
            for c in sdata.get('classes', []):
                classroom = class_cache.get(c['class_name'])
                if classroom:
                    ClassStudent.objects.get_or_create(
                        classroom=classroom, student=user,
                    )
                    counts['students_enrolled'] += 1

            # Guardian links
            for g in sdata.get('guardians', []):
                guardian = guardian_cache.get(g['email'])
                if guardian:
                    StudentGuardian.objects.get_or_create(
                        student=user, guardian=guardian,
                        defaults={'is_primary': g.get('is_primary', False)},
                    )

    return {
        'counts': counts,
        'credentials': credentials,
    }
