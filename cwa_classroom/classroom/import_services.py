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
    School, SchoolStudent, SchoolTeacher, Department, DepartmentSubject,
    Subject, Level, ClassRoom, ClassStudent, ClassTeacher,
    Guardian, StudentGuardian,
)

logger = logging.getLogger(__name__)

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_CSV_ROWS = 5000

# All mappable columns — key is the system field, value is the display label
COLUMN_FIELDS = {
    # Required (at least first_name+last_name OR full_name OR children)
    'first_name': 'Student First Name',
    'last_name': 'Student Last Name',
    'full_name': 'Student Full Name',
    'email': 'Student Email',
    # Special — comma-separated "FirstName LastName" list (expands into multiple students)
    'children': 'Children (full names)',
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
    'teacher': 'Teacher',
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

REQUIRED_FIELDS = {'first_name', 'last_name'}
# When 'children' or 'full_name' is mapped, first_name/last_name are not required
CHILDREN_MODE_REPLACES = {'first_name', 'last_name'}
FULL_NAME_MODE_REPLACES = {'first_name', 'last_name'}

# ── Source system presets ────────────────────────────────────
# Each preset maps our system field → the CSV/XLS header name used by that system.
# To add a new source system, add an entry here — no code changes needed.

SOURCE_PRESETS = {
    'teachworks': {
        'name': 'Teachworks',
        'description': 'Import from Teachworks Students export (.xls). One student per row.',
        'mapping': {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'date_of_birth': 'Birth Date',
            'level': 'Subjects',       # Teachworks "Subjects" = our Level (Year 6, VCE Methods, etc.)
            'class_name': 'Default Service',
            'teacher': 'Teachers',
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


def _split_child_name(full_name):
    """Split 'FirstName LastName' into (first, last). Last word is last name."""
    parts = full_name.strip().split()
    if len(parts) == 0:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


def _expand_children_rows(data_rows, column_mapping):
    """If 'children' column is mapped, expand each row into one row per child.

    Each child inherits all other columns from the parent row.
    The children column contains comma-separated full names like:
    "Ryan Smith, Jane Smith"
    """
    children_idx = column_mapping.get('children')
    if children_idx is None:
        return data_rows

    expanded = []
    for row in data_rows:
        children_val = _get_cell(row, children_idx)
        if not children_val:
            expanded.append(row)
            continue
        # Split by comma
        child_names = [c.strip() for c in children_val.split(',') if c.strip()]
        for child_name in child_names:
            first_name, last_name = _split_child_name(child_name)
            # Create a new row with child name injected
            new_row = list(row)
            # We'll store child names in extra positions appended to row
            new_row.append(first_name)  # index = len(original row)
            new_row.append(last_name)   # index = len(original row) + 1
            expanded.append(new_row)
    return expanded


def validate_and_preview(data_rows, column_mapping, school):
    """
    Process CSV rows into a preview of what will be created.
    Returns dict with categorised results.
    """
    errors = []
    warnings = []

    # Mode detection
    children_mode = 'children' in column_mapping
    full_name_mode = 'full_name' in column_mapping and not children_mode

    # Check required fields are mapped
    if children_mode or full_name_mode:
        required = set()  # children/full_name handle names themselves
    else:
        required = REQUIRED_FIELDS
    for f in required:
        if f not in column_mapping:
            errors.append(f'Required column "{COLUMN_FIELDS[f]}" is not mapped.')
    if errors:
        return {'errors': errors, 'warnings': warnings}

    # Expand children column if present
    if children_mode:
        original_col_count = len(data_rows[0]) if data_rows else 0
        data_rows = _expand_children_rows(data_rows, column_mapping)
        child_first_idx = original_col_count
        child_last_idx = original_col_count + 1
    else:
        child_first_idx = None
        child_last_idx = None

    # Collect student data grouped by a unique key
    students_by_key = {}
    for row_idx, row in enumerate(data_rows, start=2):  # row 2 = first data row
        # Determine student name
        if children_mode:
            first_name = _get_cell(row, child_first_idx)
            last_name = _get_cell(row, child_last_idx)
        elif full_name_mode:
            raw_full_name = _get_cell(row, column_mapping.get('full_name'))
            if raw_full_name:
                first_name, last_name = _split_child_name(raw_full_name)
            else:
                first_name, last_name = '', ''
            # Allow explicit first/last to override if also mapped
            if column_mapping.get('first_name') is not None:
                override = _get_cell(row, column_mapping.get('first_name'))
                if override:
                    first_name = override
            if column_mapping.get('last_name') is not None:
                override = _get_cell(row, column_mapping.get('last_name'))
                if override:
                    last_name = override
        else:
            first_name = _get_cell(row, column_mapping.get('first_name'))
            last_name = _get_cell(row, column_mapping.get('last_name'))

        if not first_name:
            if children_mode:
                continue  # Empty child slot, skip
            errors.append(f'Row {row_idx}: Missing first name.')
            continue

        # Determine student email
        email = _get_cell(row, column_mapping.get('email')).lower()
        parent_email = _get_cell(row, column_mapping.get('parent1_email')).lower()

        if not email:
            if parent_email:
                # Auto-generate student email from parent email
                prefix = parent_email.split('@')[0]
                domain = parent_email.split('@')[1] if '@' in parent_email else 'local'
                child_slug = slugify(f'{first_name}-{last_name}') if last_name else slugify(first_name)
                email = f'{child_slug}.{prefix}@{domain}'.lower()
            else:
                # Generate a placeholder email from student name
                child_slug = slugify(f'{first_name}-{last_name}') if last_name else slugify(first_name)
                email = f'{child_slug}@student.local'.lower()
            warnings.append(
                f'Row {row_idx}: No student email — generated "{email}".'
            )

        if not last_name:
            # Use parent's last name as fallback
            parent_last = _get_cell(row, column_mapping.get('parent1_last_name'))
            if parent_last:
                last_name = parent_last
                warnings.append(f'Row {row_idx}: Using parent last name for {first_name}.')
            elif full_name_mode or children_mode:
                # Single-word names are OK in full_name/children mode
                last_name = ''
            else:
                errors.append(f'Row {row_idx}: Missing last name for {first_name}.')
                continue

        if email not in students_by_key:
            username = _get_cell(row, column_mapping.get('username'))
            if not username:
                # Generate firstName.lastName username
                username = slugify(
                    f'{first_name}.{last_name}'
                ).replace('-', '.')
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

            students_by_key[email] = {
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

        student = students_by_key[email]
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
                'teacher': _get_cell(row, column_mapping.get('teacher')),
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
            email__in=students_by_key.keys()
        ).values_list('email', flat=True)
    )

    students_new = []
    students_existing = []
    for email, sdata in students_by_key.items():
        if email in existing_emails:
            students_existing.append(sdata)
        else:
            students_new.append(sdata)

    # Collect unique class structures
    all_classes = {}
    for sdata in students_by_key.values():
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
    for sdata in students_by_key.values():
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


def extract_csv_structure(data_rows, column_mapping):
    """Scan CSV data and return unique subjects, levels, and class names found.

    Returns dict with:
        csv_subjects: sorted list of unique subject names
        csv_levels: sorted list of unique level names
        csv_classes: sorted list of unique class names
    """
    children_mode = 'children' in column_mapping

    # Expand children if needed (only to get correct row count; we just read structure cols)
    if children_mode:
        original_col_count = len(data_rows[0]) if data_rows else 0
        data_rows = _expand_children_rows(data_rows, column_mapping)

    subjects = set()
    levels = set()
    classes = set()
    teachers = set()

    for row in data_rows:
        s = _get_cell(row, column_mapping.get('subject'))
        if s:
            subjects.add(s)
        lv = _get_cell(row, column_mapping.get('level'))
        if lv:
            levels.add(lv)
        cn = _get_cell(row, column_mapping.get('class_name'))
        if cn:
            classes.add(cn)
        t = _get_cell(row, column_mapping.get('teacher'))
        if t:
            teachers.add(t)

    return {
        'csv_subjects': sorted(subjects),
        'csv_levels': sorted(levels),
        'csv_classes': sorted(classes),
        'csv_teachers': sorted(teachers),
    }


def build_smart_mapping_context(csv_structure, department):
    """Compare CSV structure against a department's existing subjects/levels/classes.

    Returns a context dict for the mapping wizard template with:
        - subject_scenario: 'both' | 'csv_only' | 'system_only' | 'neither'
        - level_scenario: same
        - class_scenario: same
        - system_subjects: list of {id, name}
        - system_levels: list of {id, display_name, subject_name}
        - system_classes: list of {id, name}
        - csv_subjects, csv_levels, csv_classes: from csv_structure
    """
    from .models import DepartmentSubject, DepartmentLevel, SchoolTeacher

    csv_subjects = csv_structure['csv_subjects']
    csv_levels = csv_structure['csv_levels']
    csv_classes = csv_structure['csv_classes']
    csv_teachers = csv_structure.get('csv_teachers', [])

    # System subjects linked to this department
    dept_subjects_qs = DepartmentSubject.objects.filter(
        department=department
    ).select_related('subject').order_by('order')
    system_subjects = [
        {'id': ds.subject_id, 'name': ds.subject.name}
        for ds in dept_subjects_qs if ds.subject.is_active
    ]

    # System levels linked to this department
    dept_levels_qs = DepartmentLevel.objects.filter(
        department=department
    ).select_related('level', 'level__subject').order_by('level__level_number')
    system_levels = [
        {
            'id': dl.level_id,
            'display_name': dl.local_display_name or dl.level.display_name,
            'subject_name': dl.level.subject.name if dl.level.subject else '',
        }
        for dl in dept_levels_qs
    ]

    # System classes in this department
    system_classes_qs = ClassRoom.objects.filter(
        department=department, is_active=True
    ).order_by('name')
    system_classes = [
        {'id': cr.id, 'name': cr.name}
        for cr in system_classes_qs
    ]

    def scenario(csv_list, system_list):
        has_csv = len(csv_list) > 0
        has_system = len(system_list) > 0
        if has_csv and has_system:
            return 'both'
        if has_csv and not has_system:
            return 'csv_only'
        if not has_csv and has_system:
            return 'system_only'
        return 'neither'

    # System teachers in this school (including HoD)
    system_teachers_qs = SchoolTeacher.objects.filter(
        school=department.school, is_active=True,
    ).select_related('teacher').order_by('teacher__first_name')
    system_teachers = [
        {
            'id': st.teacher_id,
            'name': f'{st.teacher.first_name} {st.teacher.last_name}'.strip(),
            'role': st.role,
            'username': st.teacher.username,
        }
        for st in system_teachers_qs
    ]

    # Auto-map: match CSV values to system values by normalized name
    def _auto_match(csv_list, system_list, name_key='name'):
        """Return {csv_value: system_id} for exact or fuzzy matches."""
        matches = {}
        sys_lookup = {}
        for s in system_list:
            key = s[name_key].strip().lower()
            sys_lookup[key] = s['id']
            # Also index without common prefixes/suffixes for fuzzy match
            for prefix in ('year ', 'yr '):
                if key.startswith(prefix):
                    sys_lookup[key[len(prefix):]] = s['id']

        for csv_val in csv_list:
            norm = csv_val.strip().lower()
            if norm in sys_lookup:
                matches[csv_val] = sys_lookup[norm]
            else:
                # Try without 'year '/'yr ' prefix
                for prefix in ('year ', 'yr '):
                    if norm.startswith(prefix) and norm[len(prefix):] in sys_lookup:
                        matches[csv_val] = sys_lookup[norm[len(prefix):]]
                        break
        return matches

    auto_map_subjects = _auto_match(csv_subjects, system_subjects, 'name')
    auto_map_levels = _auto_match(csv_levels, system_levels, 'display_name')
    auto_map_classes = _auto_match(csv_classes, system_classes, 'name')
    auto_map_teachers = _auto_match(csv_teachers, system_teachers, 'name')

    return {
        'subject_scenario': scenario(csv_subjects, system_subjects),
        'level_scenario': scenario(csv_levels, system_levels),
        'class_scenario': scenario(csv_classes, system_classes),
        'teacher_scenario': scenario(csv_teachers, system_teachers),
        'system_subjects': system_subjects,
        'system_levels': system_levels,
        'system_classes': system_classes,
        'system_teachers': system_teachers,
        'csv_subjects': csv_subjects,
        'csv_levels': csv_levels,
        'csv_classes': csv_classes,
        'csv_teachers': csv_teachers,
        'auto_map_subjects': auto_map_subjects,
        'auto_map_levels': auto_map_levels,
        'auto_map_classes': auto_map_classes,
        'auto_map_teachers': auto_map_teachers,
    }


def apply_structure_mapping(preview_data, structure_mapping, department):
    """Apply user's mapping choices to preview_data before execution.

    structure_mapping is a dict with:
        department_id: int
        subject_map: {csv_subject_name: system_subject_id or 'create'}
        level_map: {csv_level_name: system_level_id or 'create'}
        class_map: {csv_class_name: system_class_id or 'create'}
        teacher_map: {csv_teacher_name: system_user_id or 'create'}
        dummy_subject: True if we need to create a dummy subject
        dummy_level: True if we need to create a dummy level
        dummy_class: True if we need to create a dummy class
    """
    preview_data['structure_mapping'] = structure_mapping
    preview_data['target_department_id'] = department.id
    preview_data['target_department_name'] = department.name
    return preview_data


def execute_import(preview_data, school, uploaded_by):
    """
    Execute the import in a single transaction.
    Returns dict with counts and credentials list.

    If preview_data contains 'structure_mapping', the department-scoped
    smart mapping is used instead of the generic CSV-driven creation.
    """
    from django.db import models as db_models
    from .models import DepartmentLevel

    credentials = []
    counts = {
        'students_created': 0,
        'students_enrolled': 0,
        'classes_created': 0,
        'departments_created': 0,
        'subjects_created': 0,
        'levels_created': 0,
        'guardians_created': 0,
        'errors': [],
    }

    role_student, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={'display_name': 'Student'},
    )

    structure_mapping = preview_data.get('structure_mapping')

    with transaction.atomic():
        if structure_mapping:
            # ── Department-scoped smart import ──
            target_dept = Department.objects.get(id=structure_mapping['department_id'])
            dept_cache = {target_dept.name: target_dept}
            # Also cache all school departments
            for dept in Department.objects.filter(school=school):
                dept_cache[dept.name] = dept

            # Resolve subject mapping
            subject_map = structure_mapping.get('subject_map', {})
            subject_cache = {}
            # Cache all existing subjects by id for lookups
            existing_subjects_by_id = {s.id: s for s in Subject.objects.filter(
                db_models.Q(school=school) | db_models.Q(school__isnull=True)
            )}
            for csv_name, target in subject_map.items():
                if target == 'create':
                    subj, created = Subject.objects.get_or_create(
                        school=school, slug=slugify(csv_name),
                        defaults={'name': csv_name, 'is_active': True},
                    )
                    if created:
                        counts['subjects_created'] += 1
                    DepartmentSubject.objects.get_or_create(
                        department=target_dept, subject=subj,
                    )
                    subject_cache[csv_name] = subj
                else:
                    # target is a system subject id
                    subj = existing_subjects_by_id.get(int(target))
                    if subj:
                        subject_cache[csv_name] = subj
                        DepartmentSubject.objects.get_or_create(
                            department=target_dept, subject=subj,
                        )

            # Handle dummy subject
            if structure_mapping.get('dummy_subject'):
                dummy_subj, created = Subject.objects.get_or_create(
                    school=school, slug=slugify(f'{target_dept.name}-general'),
                    defaults={'name': f'{target_dept.name} General', 'is_active': True},
                )
                if created:
                    counts['subjects_created'] += 1
                DepartmentSubject.objects.get_or_create(
                    department=target_dept, subject=dummy_subj,
                )
                subject_cache['__dummy__'] = dummy_subj

            # Resolve level mapping
            level_map = structure_mapping.get('level_map', {})
            level_cache = {}
            existing_levels_by_id = {l.id: l for l in Level.objects.all()}
            next_level_num = (Level.objects.aggregate(
                m=models.Max('level_number'))['m'] or 0) + 1

            for csv_name, target in level_map.items():
                if target == 'create':
                    lvl, created = Level.objects.get_or_create(
                        display_name=csv_name,
                        defaults={
                            'level_number': next_level_num,
                            'subject': subject_cache.get('__dummy__') or next(iter(subject_cache.values()), None),
                            'school': school,
                        },
                    )
                    if created:
                        next_level_num += 1
                        counts['levels_created'] += 1
                    DepartmentLevel.objects.get_or_create(
                        department=target_dept, level=lvl,
                    )
                    level_cache[csv_name.lower()] = lvl
                else:
                    lvl = existing_levels_by_id.get(int(target))
                    if lvl:
                        level_cache[csv_name.lower()] = lvl
                        DepartmentLevel.objects.get_or_create(
                            department=target_dept, level=lvl,
                        )

            # Handle dummy level
            if structure_mapping.get('dummy_level'):
                base_subj = subject_cache.get('__dummy__') or next(iter(subject_cache.values()), None)
                dummy_lvl, created = Level.objects.get_or_create(
                    display_name=f'{target_dept.name} General',
                    defaults={
                        'level_number': next_level_num,
                        'subject': base_subj,
                        'school': school,
                    },
                )
                if created:
                    counts['levels_created'] += 1
                DepartmentLevel.objects.get_or_create(
                    department=target_dept, level=dummy_lvl,
                )
                level_cache['__dummy__'] = dummy_lvl

            # Resolve class mapping
            class_map = structure_mapping.get('class_map', {})
            class_cache = {}
            existing_classes_by_id = {
                cr.id: cr for cr in ClassRoom.objects.filter(school=school)
            }

            for csv_name, target in class_map.items():
                if target == 'create':
                    # Determine subject/level for the new class
                    first_subj = next(iter(subject_cache.values()), None)
                    classroom = ClassRoom.objects.create(
                        name=csv_name,
                        school=school,
                        department=target_dept,
                        subject=first_subj,
                        created_by=uploaded_by,
                    )
                    # Link first available level
                    first_lvl = next(iter(level_cache.values()), None)
                    if first_lvl:
                        classroom.levels.add(first_lvl)
                    class_cache[csv_name] = classroom
                    counts['classes_created'] += 1
                else:
                    cr = existing_classes_by_id.get(int(target))
                    if cr:
                        class_cache[csv_name] = cr

            # Handle dummy class
            if structure_mapping.get('dummy_class'):
                first_subj = next(iter(subject_cache.values()), None)
                dummy_cr = ClassRoom.objects.create(
                    name=f'{target_dept.name} General',
                    school=school,
                    department=target_dept,
                    subject=first_subj,
                    created_by=uploaded_by,
                )
                first_lvl = next(iter(level_cache.values()), None)
                if first_lvl:
                    dummy_cr.levels.add(first_lvl)
                class_cache['__dummy__'] = dummy_cr
                counts['classes_created'] += 1

            # Also cache existing classes by name
            for cr in ClassRoom.objects.filter(school=school):
                if cr.name not in class_cache:
                    class_cache[cr.name] = cr

            # Resolve teacher mapping
            teacher_map = structure_mapping.get('teacher_map', {})
            teacher_cache = {}  # csv_teacher_name -> user object
            teacher_user_ids = [int(v) for v in teacher_map.values() if v and v != 'create']
            existing_users_by_id = {u.id: u for u in CustomUser.objects.filter(id__in=teacher_user_ids)}
            role_teacher, _ = Role.objects.get_or_create(
                name=Role.TEACHER, defaults={'display_name': 'Teacher'},
            )

            # Default teacher (HoD) for unmapped classes
            hod_user = target_dept.head

            for csv_name, target in teacher_map.items():
                if target == 'create':
                    # Create new teacher user from full name
                    first_name, last_name = _split_child_name(csv_name)
                    t_slug = slugify(f'{first_name}-{last_name}') if last_name else slugify(first_name)
                    t_email = f'{t_slug}@teacher.local'
                    t_username = t_slug.replace('-', '_')
                    suffix = 1
                    while CustomUser.objects.filter(username=t_username).exists():
                        t_username = f'{t_slug.replace("-", "_")}{suffix}'
                        suffix += 1
                    t_password = get_random_string(10)
                    teacher_user = CustomUser.objects.create_user(
                        username=t_username, email=t_email,
                        password=t_password,
                        first_name=first_name, last_name=last_name,
                    )
                    UserRole.objects.get_or_create(user=teacher_user, role=role_teacher)
                    SchoolTeacher.objects.get_or_create(
                        school=school, teacher=teacher_user,
                        defaults={'role': 'teacher', 'is_active': True},
                    )
                    teacher_cache[csv_name] = teacher_user
                    counts['teachers_created'] = counts.get('teachers_created', 0) + 1
                else:
                    user = existing_users_by_id.get(int(target))
                    if user:
                        teacher_cache[csv_name] = user

            # Link teachers to classes via ClassTeacher
            # Build a map: class_name -> set of teacher names from the CSV data
            class_teacher_names = {}
            all_students = preview_data.get('students_new', []) + preview_data.get('students_existing', [])
            for sdata in all_students:
                for c in sdata.get('classes', []):
                    t_name = c.get('teacher', '')
                    if t_name and c['class_name'] in class_cache:
                        class_teacher_names.setdefault(c['class_name'], set()).add(t_name)

            for class_name, t_names in class_teacher_names.items():
                classroom = class_cache.get(class_name)
                if not classroom:
                    continue
                for t_name in t_names:
                    teacher_user = teacher_cache.get(t_name)
                    if teacher_user:
                        ClassTeacher.objects.get_or_create(
                            classroom=classroom, teacher=teacher_user,
                        )

            # Classes with no teacher mapped — assign HoD
            if hod_user:
                for class_name, classroom in class_cache.items():
                    if class_name == '__dummy__':
                        ClassTeacher.objects.get_or_create(
                            classroom=classroom, teacher=hod_user,
                        )
                    elif class_name not in class_teacher_names:
                        ClassTeacher.objects.get_or_create(
                            classroom=classroom, teacher=hod_user,
                        )

        else:
            # ── Original generic import (no structure mapping) ──
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
            for subj in Subject.objects.filter(
                db_models.Q(school=school) | db_models.Q(school__isnull=True)
            ):
                subject_cache[subj.name] = subj

            # Link subjects to departments
            for cls_data in preview_data['classes_new'] + preview_data['classes_existing']:
                dept_name = cls_data.get('department', '')
                subj_name = cls_data.get('subject', '')
                if dept_name and subj_name and dept_name in dept_cache and subj_name in subject_cache:
                    DepartmentSubject.objects.get_or_create(
                        department=dept_cache[dept_name],
                        subject=subject_cache[subj_name],
                    )

            # 3. Resolve levels
            level_cache = {}
            for lvl in Level.objects.all():
                level_cache[lvl.display_name.lower()] = lvl
                level_cache[str(lvl.level_number)] = lvl

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
                level_key = cls_data.get('level', '').lower()
                if level_key and level_key in level_cache:
                    classroom.levels.add(level_cache[level_key])
                class_cache[cls_data['class_name']] = classroom
                counts['classes_created'] += 1
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
                # Generate username as firstName.lastName
                base_username = slugify(
                    f"{sdata['first_name']}.{sdata['last_name']}"
                ).replace('-', '.')
                if not base_username:
                    base_username = sdata.get('username', email.split('@')[0])
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
                user.must_change_password = True
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
            ss, ss_created = SchoolStudent.objects.get_or_create(
                school=school, student=user,
                defaults={'opening_balance': sdata.get('opening_balance', Decimal('0'))},
            )
            # Store pending password for publish email (new users only)
            if is_new and password and ss_created:
                ss.pending_password = password
                ss.save(update_fields=['pending_password'])

            # ClassStudent enrollments
            enrolled = False
            for c in sdata.get('classes', []):
                classroom = class_cache.get(c['class_name'])
                if classroom:
                    ClassStudent.objects.get_or_create(
                        classroom=classroom, student=user,
                    )
                    counts['students_enrolled'] += 1
                    enrolled = True

            # If no class enrollment and we have a dummy class, enroll there
            if not enrolled and '__dummy__' in class_cache:
                ClassStudent.objects.get_or_create(
                    classroom=class_cache['__dummy__'], student=user,
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


# ── Balance Import ──────────────────────────────────────────

BALANCE_COLUMN_FIELDS = {
    'first_name': 'Parent First Name',
    'last_name': 'Parent Last Name',
    'balance': 'Balance',
    'net_invoices': 'Net Invoices',
    'net_payments': 'Net Payments',
    'external_id': 'Customer ID',
    'status': 'Customer Status',
}

BALANCE_REQUIRED_FIELDS = {'first_name', 'last_name', 'balance'}

BALANCE_PRESETS = {
    'teachworks': {
        'name': 'Teachworks',
        'description': 'Import from Teachworks Customer Balances export (.xls).',
        'mapping': {
            'external_id': 'Customer ID',
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'balance': 'Balance',
            'net_invoices': 'Net Invoices',
            'net_payments': 'Net Payments',
            'status': 'Customer Status',
        },
    },
}


def apply_balance_preset(preset_key, headers):
    """Apply a balance preset to map column headers. Returns {field: col_index}."""
    preset = BALANCE_PRESETS.get(preset_key.lower())
    if not preset:
        return {}
    header_lower = {h.lower(): i for i, h in enumerate(headers)}
    mapping = {}
    for system_field, csv_header in preset['mapping'].items():
        idx = header_lower.get(csv_header.lower())
        if idx is not None:
            mapping[system_field] = idx
    return mapping


def _build_balance_column_mapping(post_data):
    """Build column_mapping dict from POST data for balance import."""
    mapping = {}
    for field in BALANCE_COLUMN_FIELDS:
        val = post_data.get(f'col_{field}', '')
        if val != '' and val != '-1':
            mapping[field] = int(val)
    return mapping


def validate_balance_preview(data_rows, column_mapping, school):
    """
    Match balance rows to guardians by name, resolve to students.
    Returns preview dict.
    """
    from classroom.models import Guardian, StudentGuardian, SchoolStudent

    errors = []
    warnings = []

    # Check required fields
    for f in BALANCE_REQUIRED_FIELDS:
        if f not in column_mapping:
            errors.append(f'Required column "{BALANCE_COLUMN_FIELDS[f]}" is not mapped.')
    if errors:
        return {'errors': errors, 'warnings': warnings}

    # Build guardian lookup by (first_name_lower, last_name_lower)
    guardians = Guardian.objects.filter(school=school).prefetch_related(
        'students__student', 'students__student__school_students'
    )
    guardian_lookup = {}
    for g in guardians:
        key = (g.first_name.lower().strip(), g.last_name.lower().strip())
        if key not in guardian_lookup:
            guardian_lookup[key] = g

    matched = []
    unmatched = []

    for row_idx, row in enumerate(data_rows, start=2):
        first_name = _get_cell(row, column_mapping.get('first_name')).strip()
        last_name = _get_cell(row, column_mapping.get('last_name')).strip()
        balance_str = _get_cell(row, column_mapping.get('balance'))

        if not first_name or not last_name:
            warnings.append(f'Row {row_idx}: Missing name, skipped.')
            continue

        try:
            balance = Decimal(str(balance_str).replace(',', ''))
        except (InvalidOperation, ValueError):
            warnings.append(f'Row {row_idx}: Invalid balance "{balance_str}", skipped.')
            continue

        # Try to match guardian
        key = (first_name.lower(), last_name.lower())
        guardian = guardian_lookup.get(key)

        if not guardian:
            unmatched.append({
                'row': row_idx,
                'parent_name': f'{first_name} {last_name}',
                'balance': balance,
                'external_id': _get_cell(row, column_mapping.get('external_id')),
            })
            continue

        # Get the first student linked to this guardian
        student_guardian = StudentGuardian.objects.filter(
            guardian=guardian
        ).select_related('student').order_by('id').first()

        if not student_guardian:
            unmatched.append({
                'row': row_idx,
                'parent_name': f'{first_name} {last_name}',
                'balance': balance,
                'external_id': _get_cell(row, column_mapping.get('external_id')),
                'reason': 'Guardian found but no linked students',
            })
            continue

        student = student_guardian.student
        school_student = SchoolStudent.objects.filter(
            school=school, student=student
        ).first()

        if not school_student:
            unmatched.append({
                'row': row_idx,
                'parent_name': f'{first_name} {last_name}',
                'balance': balance,
                'reason': f'Student {student.first_name} {student.last_name} not enrolled in this school',
            })
            continue

        matched.append({
            'row': row_idx,
            'parent_name': f'{first_name} {last_name}',
            'balance': balance,
            'student_name': f'{student.first_name} {student.last_name}',
            'student_email': student.email,
            'student_id': student.id,
            'school_student_id': school_student.id,
            'current_balance': school_student.opening_balance,
            'external_id': _get_cell(row, column_mapping.get('external_id')),
        })

    return {
        'matched': matched,
        'unmatched': unmatched,
        'errors': errors,
        'warnings': warnings,
        'total_balance': sum(m['balance'] for m in matched),
        'total_rows': len(data_rows),
    }


def execute_balance_import(matched_items, school):
    """Apply opening balances to matched students."""
    from classroom.models import SchoolStudent
    from classroom.invoicing_services import set_opening_balance

    results = {
        'updated': 0,
        'skipped': 0,
        'errors': [],
        'details': [],
    }

    for item in matched_items:
        try:
            school_student = SchoolStudent.objects.get(id=item['school_student_id'])
            set_opening_balance(school_student, item['balance'])
            results['updated'] += 1
            results['details'].append({
                'student_name': item['student_name'],
                'parent_name': item['parent_name'],
                'balance': item['balance'],
                'status': 'updated',
            })
        except SchoolStudent.DoesNotExist:
            results['errors'].append(f'Student record {item["school_student_id"]} not found.')
        except Exception as e:
            results['errors'].append(f'{item["student_name"]}: {str(e)}')
            results['skipped'] += 1

    return results


# ── Teacher Import ──────────────────────────────────────────

TEACHER_COLUMN_FIELDS = {
    'first_name': 'First Name',
    'last_name': 'Last Name',
    'email': 'Email',
    'phone': 'Mobile Phone',
    'position': 'Position / Role',
    'specialty': 'Subjects / Specialty',
    'status': 'Status',
    'type': 'Type (Teacher / Staff)',
}

TEACHER_REQUIRED_FIELDS = {'first_name', 'last_name', 'email'}

# Map Teachworks Position values → SchoolTeacher role
POSITION_ROLE_MAP = {
    'principal teacher': 'head_of_institute',
    'principal': 'head_of_institute',
    'admin': 'accountant',
    'head admin': 'accountant',
    'senior teacher': 'senior_teacher',
    'junior teacher': 'junior_teacher',
}

TEACHER_PRESETS = {
    'teachworks': {
        'name': 'Teachworks',
        'description': 'Import from Teachworks Employees export (.xls).',
        'mapping': {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email',
            'phone': 'Mobile Phone',
            'position': 'Position',
            'specialty': 'Subjects',
            'status': 'Status',
            'type': 'Type',
        },
    },
}


def apply_teacher_preset(preset_key, headers):
    """Apply a teacher preset to map column headers. Returns {field: col_index}."""
    preset = TEACHER_PRESETS.get(preset_key.lower())
    if not preset:
        return {}
    header_lower = {h.strip().lower(): i for i, h in enumerate(headers)}
    mapping = {}
    for system_field, csv_header in preset['mapping'].items():
        idx = header_lower.get(csv_header.lower())
        if idx is not None:
            mapping[system_field] = idx
    return mapping


def _build_teacher_column_mapping(post_data):
    """Build column_mapping dict from POST data for teacher import."""
    mapping = {}
    for field in TEACHER_COLUMN_FIELDS:
        val = post_data.get(f'col_{field}', '')
        if val != '' and val != '-1':
            mapping[field] = int(val)
    return mapping


def _map_position_to_role(position_str):
    """Map a Teachworks Position string to a SchoolTeacher role."""
    if not position_str:
        return 'teacher'
    return POSITION_ROLE_MAP.get(position_str.strip().lower(), 'teacher')


def _role_to_system_role(school_role):
    """Map a SchoolTeacher role to the corresponding system Role name."""
    if school_role == 'head_of_institute':
        return Role.HEAD_OF_INSTITUTE
    elif school_role == 'head_of_department':
        return Role.HEAD_OF_DEPARTMENT
    elif school_role == 'accountant':
        return Role.ACCOUNTANT
    return Role.TEACHER


def validate_teacher_preview(data_rows, column_mapping, school):
    """
    Validate teacher import data and categorize as new/existing.
    Returns preview dict with teachers_new, teachers_existing, errors, warnings.
    """
    errors = []
    warnings = []
    teachers_new = []
    teachers_existing = []

    # Validate required fields are mapped
    mapped_fields = set(column_mapping.keys())
    missing = TEACHER_REQUIRED_FIELDS - mapped_fields
    if missing:
        labels = [TEACHER_COLUMN_FIELDS.get(f, f) for f in missing]
        errors.append(f'Required columns not mapped: {", ".join(labels)}')
        return {'teachers_new': [], 'teachers_existing': [], 'errors': errors, 'warnings': warnings}

    seen_emails = set()
    for row_idx, row in enumerate(data_rows, start=2):  # row 1 = header
        def _cell(field):
            idx = column_mapping.get(field)
            if idx is None or idx >= len(row):
                return ''
            return str(row[idx]).strip()

        first_name = _cell('first_name')
        last_name = _cell('last_name')
        email = _cell('email')
        phone = _cell('phone')
        position = _cell('position')
        specialty = _cell('specialty')
        status = _cell('status')
        emp_type = _cell('type')

        # Skip inactive
        if status and status.lower() not in ('active', ''):
            warnings.append(f'Row {row_idx}: {first_name} {last_name} skipped (status: {status})')
            continue

        if not first_name or not last_name:
            errors.append(f'Row {row_idx}: Missing first or last name')
            continue
        if not email:
            errors.append(f'Row {row_idx}: {first_name} {last_name} — missing email')
            continue

        email = email.lower()
        if email in seen_emails:
            warnings.append(f'Row {row_idx}: Duplicate email {email} in file — skipped')
            continue
        seen_emails.add(email)

        role = _map_position_to_role(position)

        teacher_data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': phone,
            'role': role,
            'role_display': dict(SchoolTeacher.ROLE_CHOICES).get(role, role),
            'specialty': specialty,
            'position_raw': position,
            'type': emp_type,
            'row': row_idx,
        }

        # Check if user already exists
        if CustomUser.objects.filter(email=email).exists():
            # Check if already linked to this school
            user = CustomUser.objects.get(email=email)
            already_linked = SchoolTeacher.objects.filter(school=school, teacher=user).exists()
            teacher_data['already_linked'] = already_linked
            if already_linked:
                warnings.append(
                    f'Row {row_idx}: {first_name} {last_name} ({email}) already in this school — will be skipped'
                )
            teachers_existing.append(teacher_data)
        else:
            teachers_new.append(teacher_data)

    return {
        'teachers_new': teachers_new,
        'teachers_existing': teachers_existing,
        'errors': errors,
        'warnings': warnings,
    }


@transaction.atomic
def execute_teacher_import(preview_data, school, imported_by):
    """
    Create teacher accounts and link them to the school.
    Returns dict with counts and credentials for new teachers.
    """
    credentials = []
    counts = {
        'teachers_created': 0,
        'teachers_linked': 0,
        'teachers_skipped': 0,
    }

    all_teachers = preview_data['teachers_new'] + preview_data['teachers_existing']

    for tdata in all_teachers:
        email = tdata['email']
        is_new = not CustomUser.objects.filter(email=email).exists()

        if is_new:
            password = get_random_string(10)
            base_username = slugify(
                f"{tdata['first_name']}.{tdata['last_name']}"
            ).replace('-', '.')
            if not base_username:
                base_username = email.split('@')[0]
            username = base_username
            suffix = 1
            while CustomUser.objects.filter(username=username).exists():
                username = f'{base_username}{suffix}'
                suffix += 1

            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=tdata['first_name'],
                last_name=tdata['last_name'],
            )
            user.must_change_password = True
            if tdata.get('phone'):
                user.phone = tdata['phone']
            user.save()

            # Assign system role
            system_role_name = _role_to_system_role(tdata['role'])
            role_obj, _ = Role.objects.get_or_create(
                name=system_role_name,
                defaults={'display_name': system_role_name.replace('_', ' ').title()},
            )
            UserRole.objects.get_or_create(user=user, role=role_obj)

            credentials.append({
                'username': username,
                'email': email,
                'password': password,
                'first_name': tdata['first_name'],
                'last_name': tdata['last_name'],
                'role': tdata['role_display'],
            })
            counts['teachers_created'] += 1
        else:
            user = CustomUser.objects.get(email=email)
            password = None

        # Link to school (skip if already linked)
        st, created = SchoolTeacher.objects.get_or_create(
            school=school, teacher=user,
            defaults={
                'role': tdata['role'],
                'specialty': tdata.get('specialty', ''),
                'is_active': True,
            },
        )
        # Store pending password for publish email (new users only)
        if is_new and password and created:
            st.pending_password = password
            st.save(update_fields=['pending_password'])
        if created:
            counts['teachers_linked'] += 1
            # Ensure user has teacher system role
            if is_new is False:
                system_role_name = _role_to_system_role(tdata['role'])
                role_obj, _ = Role.objects.get_or_create(
                    name=system_role_name,
                    defaults={'display_name': system_role_name.replace('_', ' ').title()},
                )
                UserRole.objects.get_or_create(user=user, role=role_obj)
        else:
            counts['teachers_skipped'] += 1

    return {
        'counts': counts,
        'credentials': credentials,
    }
