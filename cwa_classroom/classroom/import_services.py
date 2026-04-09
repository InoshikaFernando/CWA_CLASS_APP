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
    Guardian, StudentGuardian, ParentStudent,
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
    _generated_email_counts = {}  # base_email -> count, for collision numbering
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

        # If student email is the same as parent email (common in Teachworks exports),
        # treat it as missing — generate a unique student placeholder instead.
        if email and email == parent_email:
            email = ''

        if not email:
            child_slug = slugify(first_name) if first_name else slugify(f'{first_name}-{last_name}')
            if parent_email and '@' in parent_email:
                # Use plus-addressing: parent+firstName@domain
                # e.g. test@example.com -> test+ryan@example.com
                # Delivers to parent inbox, unique per child, works for siblings
                prefix = parent_email.split('@')[0]
                domain = parent_email.split('@')[1]
                base_email = f'{prefix}+{child_slug}@{domain}'.lower()
            else:
                base_email = f'{child_slug}@student.local'.lower()

            # Handle collisions: if the same base was already generated, append 1, 2, ...
            if base_email not in _generated_email_counts:
                _generated_email_counts[base_email] = 0
                email = base_email
            else:
                _generated_email_counts[base_email] += 1
                n = _generated_email_counts[base_email]
                # Insert the number before the @: test+joanna1@example.com
                local, domain_part = base_email.split('@', 1)
                email = f'{local}{n}@{domain_part}'

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

    # Categorise entities as new or existing (case-insensitive email match)
    existing_emails = set(
        e.lower() for e in CustomUser.objects.filter(
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


def _auto_create_teacher(full_name, school, role_teacher, teacher_cache, counts):
    """Auto-create a placeholder teacher account from a full name.

    Creates a CustomUser with @teacher.local email, assigns TEACHER role,
    and creates SchoolTeacher link. Returns the created user or None.
    """
    first_name, last_name = _split_child_name(full_name)
    if not first_name:
        return None

    # Check if already exists at school by name
    existing_st = SchoolTeacher.objects.filter(
        school=school,
        teacher__first_name__iexact=first_name,
        teacher__last_name__iexact=last_name,
        is_active=True,
    ).select_related('teacher').first()
    if existing_st:
        teacher_cache[full_name] = existing_st.teacher
        return existing_st.teacher

    t_slug = slugify(f'{first_name}-{last_name}') if last_name else slugify(first_name)
    t_email = f'{t_slug}@teacher.local'

    # Reuse existing placeholder teacher if email already exists
    existing_user = CustomUser.objects.filter(email__iexact=t_email).first()
    if existing_user:
        SchoolTeacher.objects.get_or_create(
            school=school, teacher=existing_user,
            defaults={'role': 'teacher', 'is_active': True},
        )
        teacher_cache[full_name] = existing_user
        return existing_user

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
    teacher_user.must_change_password = True
    teacher_user.save(update_fields=['must_change_password'])
    UserRole.objects.get_or_create(user=teacher_user, role=role_teacher)
    st, created = SchoolTeacher.objects.get_or_create(
        school=school, teacher=teacher_user,
        defaults={'role': 'teacher', 'is_active': True},
    )
    if created and t_password:
        st.pending_password = t_password
        st.save(update_fields=['pending_password'])
    teacher_cache[full_name] = teacher_user
    counts['teachers_created'] = counts.get('teachers_created', 0) + 1
    return teacher_user


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
    parent_credentials = []
    counts = {
        'students_created': 0,
        'students_enrolled': 0,
        'classes_created': 0,
        'departments_created': 0,
        'subjects_created': 0,
        'levels_created': 0,
        'guardians_created': 0,
        'parents_created': 0,
        'errors': [],
    }

    role_student, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={'display_name': 'Student'},
    )
    role_parent, _ = Role.objects.get_or_create(
        name=Role.PARENT, defaults={'display_name': 'Parent'},
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

            # Apply global subject links (optional — links local subject to global Mathematics etc.)
            global_subject_map = structure_mapping.get('global_subject_map', {})
            for csv_name, global_subj_id in global_subject_map.items():
                if global_subj_id and global_subj_id != 'none':
                    local_subj = subject_cache.get(csv_name)
                    global_subj = Subject.objects.filter(id=int(global_subj_id), school__isnull=True).first()
                    if local_subj and global_subj and local_subj.global_subject_id != global_subj.id:
                        local_subj.global_subject = global_subj
                        local_subj.save(update_fields=['global_subject'])

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

            # Apply global level links — builds a cache: csv_level_name -> global Level
            global_level_map = structure_mapping.get('global_level_map', {})
            global_level_cache = {}  # csv_level_name (lower) -> global Level object
            for csv_name, global_lvl_id in global_level_map.items():
                if global_lvl_id and global_lvl_id != 'none':
                    global_lvl = Level.objects.filter(id=int(global_lvl_id), school__isnull=True).first()
                    if global_lvl:
                        global_level_cache[csv_name.lower()] = global_lvl
                        # Ensure DepartmentLevel link exists for this global level too
                        DepartmentLevel.objects.get_or_create(
                            department=target_dept, level=global_lvl,
                            defaults={'order': global_lvl.level_number},
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
                        # Also link the matching global level (if the user mapped it)
                        for csv_lvl_name, cached_lvl in level_cache.items():
                            if cached_lvl == first_lvl and csv_lvl_name in global_level_cache:
                                classroom.levels.add(global_level_cache[csv_lvl_name])
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
                    for csv_lvl_name, cached_lvl in level_cache.items():
                        if cached_lvl == first_lvl and csv_lvl_name in global_level_cache:
                            dummy_cr.levels.add(global_level_cache[csv_lvl_name])
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

                    # Reuse existing placeholder teacher if email already exists
                    existing_teacher = CustomUser.objects.filter(email__iexact=t_email).first()
                    if existing_teacher:
                        SchoolTeacher.objects.get_or_create(
                            school=school, teacher=existing_teacher,
                            defaults={'role': 'teacher', 'is_active': True},
                        )
                        teacher_cache[csv_name] = existing_teacher
                    else:
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
                    if not teacher_user:
                        # Auto-create placeholder teacher from name
                        teacher_user = _auto_create_teacher(
                            t_name, school, role_teacher, teacher_cache, counts,
                        )
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

            # 4b. Link teachers to classes (generic path)
            role_teacher, _ = Role.objects.get_or_create(
                name=Role.TEACHER, defaults={'display_name': 'Teacher'},
            )
            teacher_cache = {}
            all_students_g = preview_data.get('students_new', []) + preview_data.get('students_existing', [])
            for sdata in all_students_g:
                for c in sdata.get('classes', []):
                    t_name = c.get('teacher', '')
                    if t_name and c['class_name'] in class_cache:
                        if t_name not in teacher_cache:
                            # Try to find existing teacher at school by name
                            first_name, last_name = _split_child_name(t_name)
                            existing_st = SchoolTeacher.objects.filter(
                                school=school,
                                teacher__first_name__iexact=first_name,
                                teacher__last_name__iexact=last_name,
                                is_active=True,
                            ).select_related('teacher').first()
                            if existing_st:
                                teacher_cache[t_name] = existing_st.teacher
                            else:
                                teacher_cache[t_name] = _auto_create_teacher(
                                    t_name, school, role_teacher, teacher_cache, counts,
                                )
                        teacher_user = teacher_cache.get(t_name)
                        if teacher_user:
                            ClassTeacher.objects.get_or_create(
                                classroom=class_cache[c['class_name']],
                                teacher=teacher_user,
                            )

        # 5. Create guardians + parent user accounts
        guardian_cache = {}
        parent_user_cache = {}  # email → CustomUser for ParentStudent linking later
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

            # Create or reuse a CustomUser account for this guardian
            g_email = g_data['email']
            existing_user = CustomUser.objects.filter(email__iexact=g_email).first()
            if existing_user:
                # Reuse existing account — just ensure parent role is assigned
                UserRole.objects.get_or_create(user=existing_user, role=role_parent)
                parent_user_cache[g_email] = existing_user
            else:
                g_password = get_random_string(10)
                base_username = slugify(
                    f"{g_data['first_name']}.{g_data['last_name']}"
                ).replace('-', '.')
                if not base_username:
                    base_username = g_email.split('@')[0]
                g_username = base_username
                suffix = 1
                while CustomUser.objects.filter(username=g_username).exists():
                    g_username = f'{base_username}{suffix}'
                    suffix += 1
                parent_user = CustomUser.objects.create_user(
                    username=g_username,
                    email=g_email,
                    password=g_password,
                    first_name=g_data['first_name'],
                    last_name=g_data['last_name'],
                )
                UserRole.objects.create(user=parent_user, role=role_parent)
                parent_user_cache[g_email] = parent_user
                parent_credentials.append({
                    'username': g_username,
                    'email': g_email,
                    'password': g_password,
                    'first_name': g_data['first_name'],
                    'last_name': g_data['last_name'],
                })
                counts['parents_created'] += 1

        # Cache existing guardians
        for g in Guardian.objects.filter(school=school):
            guardian_cache[g.email] = g

        # 6-9. Create students, enroll, link guardians
        all_students = preview_data['students_new'] + preview_data['students_existing']
        new_student_emails = {s['email'] for s in preview_data['students_new']}

        # Batch-fetch existing users so we don't query per-student
        existing_user_map = {
            u.email: u for u in CustomUser.objects.filter(
                email__in=[s['email'] for s in preview_data['students_existing']]
            )
        } if preview_data['students_existing'] else {}

        # Load all usernames into memory once — avoids per-student DB round-trips
        used_usernames = set(CustomUser.objects.values_list('username', flat=True))

        for sdata in all_students:
            email = sdata['email']
            is_new = email in new_student_emails

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
                while username in used_usernames:
                    username = f'{base_username}{suffix}'
                    suffix += 1
                used_usernames.add(username)

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
                user = existing_user_map.get(email) or CustomUser.objects.filter(email__iexact=email).first()
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

            # Guardian links (contact record + ParentStudent user link)
            guardian_list = sdata.get('guardians', [])
            for idx, g in enumerate(guardian_list):
                g_email = g['email']
                guardian = guardian_cache.get(g_email)
                if guardian:
                    StudentGuardian.objects.get_or_create(
                        student=user, guardian=guardian,
                        defaults={'is_primary': g.get('is_primary', False)},
                    )
                parent_user = parent_user_cache.get(g_email)
                if parent_user:
                    # Check max 2 active parents per student per school
                    active_count = ParentStudent.objects.filter(
                        student=user, school=school, is_active=True,
                    ).count()
                    if active_count < 2:
                        is_primary = (idx == 0)
                        ParentStudent.objects.get_or_create(
                            parent=parent_user, student=user, school=school,
                            defaults={
                                'relationship': g.get('relationship', 'guardian'),
                                'is_primary_contact': is_primary,
                                'created_by': uploaded_by,
                            },
                        )

    return {
        'counts': counts,
        'credentials': credentials,
        'parent_credentials': parent_credentials,
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
        'guardian_students__student', 'guardian_students__student__school_student_entries'
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

        # Check if user already exists (case-insensitive)
        if CustomUser.objects.filter(email__iexact=email).exists():
            # Check if already linked to this school
            user = CustomUser.objects.filter(email__iexact=email).first()
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

        # Check for placeholder teacher (created during student import)
        placeholder_st = SchoolTeacher.objects.filter(
            school=school,
            teacher__first_name__iexact=tdata['first_name'],
            teacher__last_name__iexact=tdata['last_name'],
            teacher__email__endswith='@teacher.local',
            is_active=True,
        ).select_related('teacher').first()

        if placeholder_st:
            # Update placeholder with real details and a proper password
            user = placeholder_st.teacher
            user.email = email
            if tdata.get('phone'):
                user.phone = tdata['phone']
            # Generate a real password so the admin can share credentials
            password = get_random_string(10)
            user.set_password(password)
            user.must_change_password = True
            user.save(update_fields=['email', 'phone', 'password', 'must_change_password'])
            is_new = False
            # Include in credentials CSV so admin can distribute login details
            credentials.append({
                'username': user.username,
                'email': email,
                'password': password,
                'first_name': tdata['first_name'],
                'last_name': tdata['last_name'],
                'role': tdata['role_display'],
            })
            counts['teachers_updated'] = counts.get('teachers_updated', 0) + 1
        else:
            is_new = not CustomUser.objects.filter(email__iexact=email).exists()

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
        elif not placeholder_st:
            user = CustomUser.objects.filter(email__iexact=email).first()
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
        if not created and placeholder_st:
            # Update placeholder SchoolTeacher with real role/specialty
            st.role = tdata['role']
            st.specialty = tdata.get('specialty', '')
            if password:
                st.pending_password = password
            st.save(update_fields=['role', 'specialty', 'pending_password'])
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
        elif placeholder_st:
            # Placeholder updated — ensure correct role is assigned
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


# ── Parent Import ───────────────────────────────────────────

PARENT_COLUMN_FIELDS = {
    'first_name': 'Parent First Name',
    'last_name': 'Parent Last Name',
    'email': 'Parent Email',
    'phone': 'Phone',
    'relationship': 'Relationship',
    'student_email': 'Student Email',
    'children': 'Children (names)',
    'status': 'Status',
    'address': 'Address',
    'city': 'City',
    'country': 'Country',
}

# student_email OR children must be mapped (checked in validate)
PARENT_REQUIRED_FIELDS = {'first_name', 'last_name', 'email'}

PARENT_PRESETS = {
    'teachworks': {
        'name': 'Teachworks',
        'description': 'Import from Teachworks Families export (.xls).',
        'mapping': {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email',
            'phone': 'Mobile Phone',
            'children': 'Children',
            'status': 'Status',
            'address': 'Address',
            'city': 'City',
            'country': 'Country',
        },
    },
}


def apply_parent_preset(preset_key, headers):
    """Apply a parent preset to map column headers. Returns {field: col_index}."""
    preset = PARENT_PRESETS.get(preset_key)
    if not preset:
        return {}
    header_lower = {h.lower().strip(): i for i, h in enumerate(headers)}
    mapping = {}
    for system_field, csv_header in preset['mapping'].items():
        idx = header_lower.get(csv_header.lower())
        if idx is not None:
            mapping[system_field] = idx
    return mapping


def _build_parent_column_mapping(post_data):
    """Build column_mapping dict from POST data for parent import."""
    mapping = {}
    for field in PARENT_COLUMN_FIELDS:
        val = post_data.get(f'col_{field}', '')
        if val != '' and val != '-1':
            mapping[field] = int(val)
    return mapping


PARENT_RELATIONSHIP_MAP = {
    'mother': 'mother', 'mom': 'mother', 'mum': 'mother',
    'father': 'father', 'dad': 'father',
    'guardian': 'guardian',
    'other': 'other',
}


def _find_student_at_school_by_email(student_email, school):
    """Returns CustomUser or None if student_email is not a student at school."""
    try:
        user = CustomUser.objects.get(email=student_email)
        if SchoolStudent.objects.filter(student=user, school=school, is_active=True).exists():
            return user
    except CustomUser.DoesNotExist:
        pass
    return None


def _build_student_name_lookup(school):
    """Build a lookup dict of (first_lower, last_lower) -> CustomUser for students at school."""
    lookup = {}
    for ss in SchoolStudent.objects.filter(school=school, is_active=True).select_related('student'):
        u = ss.student
        key = (u.first_name.lower().strip(), u.last_name.lower().strip())
        if key not in lookup:
            lookup[key] = u
    return lookup


def _find_student_by_name(full_name, name_lookup):
    """Find a student by full name from the pre-built lookup. Returns CustomUser or None."""
    first, last = _split_child_name(full_name)
    if not first:
        return None
    return name_lookup.get((first.lower().strip(), last.lower().strip()))


def validate_parent_preview(data_rows, column_mapping, school):
    """
    Validate parent CSV rows. Groups by parent email since one parent
    may appear on multiple rows (one row per child).

    Supports two modes:
    - student_email mapped: match students by email
    - children mapped: match students by name (comma-separated full names)

    Returns dict with: parents_new, parents_existing, errors, warnings.
    """
    errors = []
    warnings = []

    # Check required fields are mapped
    for f in PARENT_REQUIRED_FIELDS:
        if f not in column_mapping:
            errors.append(f'Required column "{PARENT_COLUMN_FIELDS[f]}" is not mapped.')

    has_student_email = 'student_email' in column_mapping
    has_children = 'children' in column_mapping
    if not has_student_email and not has_children:
        errors.append('Either "Student Email" or "Children (names)" must be mapped.')

    if errors:
        return {'parents_new': [], 'parents_existing': [], 'errors': errors, 'warnings': warnings}

    # Pre-build name lookup for children mode
    name_lookup = _build_student_name_lookup(school) if has_children else {}

    # Filter inactive rows if status column is mapped
    has_status = 'status' in column_mapping

    # First pass: group rows by parent email
    parent_groups = {}  # email -> {parent_data, children: [...]}

    for row_idx, row in enumerate(data_rows, start=2):
        # Skip inactive rows
        if has_status:
            status_val = _get_cell(row, column_mapping.get('status')).lower()
            if status_val and status_val not in ('active', ''):
                continue

        first_name = _get_cell(row, column_mapping.get('first_name'))
        last_name = _get_cell(row, column_mapping.get('last_name'))
        email = _get_cell(row, column_mapping.get('email')).lower()
        phone = _get_cell(row, column_mapping.get('phone'))
        rel_raw = _get_cell(row, column_mapping.get('relationship')).lower()
        address = _get_cell(row, column_mapping.get('address'))
        city = _get_cell(row, column_mapping.get('city'))
        country = _get_cell(row, column_mapping.get('country'))

        if not first_name:
            errors.append(f'Row {row_idx}: Missing parent first name.')
            continue
        if not last_name:
            errors.append(f'Row {row_idx}: Missing parent last name.')
            continue
        if not email or '@' not in email:
            errors.append(f'Row {row_idx}: Missing or invalid parent email.')
            continue

        relationship = PARENT_RELATIONSHIP_MAP.get(rel_raw, '')
        if rel_raw and not relationship:
            relationship = 'other'
            warnings.append(f'Row {row_idx}: Unrecognised relationship "{rel_raw}", defaulting to "other".')

        if email not in parent_groups:
            parent_groups[email] = {
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'phone': phone,
                'address': address,
                'city': city,
                'country': country,
                'children': [],
            }

        # Resolve student(s) for this row
        matched_students = []

        if has_children:
            children_val = _get_cell(row, column_mapping.get('children'))
            if children_val:
                child_names = [c.strip() for c in children_val.split(',') if c.strip()]
                for child_name in child_names:
                    student_user = _find_student_by_name(child_name, name_lookup)
                    if student_user:
                        matched_students.append((student_user, child_name))
                    else:
                        warnings.append(
                            f'Row {row_idx}: Child "{child_name}" not found at this school — skipping.'
                        )

        if has_student_email:
            student_email = _get_cell(row, column_mapping.get('student_email')).lower()
            if student_email and '@' in student_email:
                student_user = _find_student_at_school_by_email(student_email, school)
                if student_user:
                    # Avoid duplicates if also matched via children
                    existing_ids = {s[0].id for s in matched_students}
                    if student_user.id not in existing_ids:
                        matched_students.append((student_user, student_email))
                else:
                    warnings.append(
                        f'Row {row_idx}: Student "{student_email}" not found at this school — skipping.'
                    )

        if not matched_students:
            warnings.append(f'Row {row_idx}: No matching students found for {first_name} {last_name} — skipping.')
            continue

        for student_user, student_ref in matched_students:
            # Check if already linked
            already_linked = ParentStudent.objects.filter(
                parent__email=email, student=student_user, school=school, is_active=True,
            ).exists()

            # Check max 2 parents
            active_parent_count = ParentStudent.objects.filter(
                student=student_user, school=school, is_active=True,
            ).count()
            if active_parent_count >= 2 and not already_linked:
                warnings.append(
                    f'Row {row_idx}: {student_user.get_full_name()} already has 2 parents linked — will be skipped.'
                )

            # Deduplicate within this parent's children list
            existing_child_ids = {c['student_id'] for c in parent_groups[email]['children']}
            if student_user.id not in existing_child_ids:
                parent_groups[email]['children'].append({
                    'student_email': student_user.email,
                    'student_name': student_user.get_full_name() or student_ref,
                    'student_id': student_user.id,
                    'relationship': relationship,
                    'row': row_idx,
                    'already_linked': already_linked,
                    'at_max_parents': active_parent_count >= 2 and not already_linked,
                })

    # Remove parents with no matched children
    parent_groups = {e: p for e, p in parent_groups.items() if p['children']}

    # Categorise as new or existing
    existing_emails = set(
        e.lower() for e in CustomUser.objects.filter(
            email__in=parent_groups.keys()
        ).values_list('email', flat=True)
    )

    parents_new = []
    parents_existing = []
    for email, pdata in parent_groups.items():
        if email.lower() in existing_emails:
            parents_existing.append(pdata)
        else:
            parents_new.append(pdata)

    return {
        'parents_new': parents_new,
        'parents_existing': parents_existing,
        'errors': errors,
        'warnings': warnings,
    }


def execute_parent_import(preview_data, school, imported_by):
    """
    Create parent user accounts and link them to students.
    Returns dict with counts and credentials list.
    """
    credentials = []
    counts = {
        'parents_created': 0,
        'links_created': 0,
        'links_skipped': 0,
        'errors': [],
    }

    parent_role, _ = Role.objects.get_or_create(
        name=Role.PARENT, defaults={'display_name': 'Parent'},
    )

    with transaction.atomic():
        all_parents = preview_data['parents_new'] + preview_data['parents_existing']
        for pdata in all_parents:
            email = pdata['email']
            is_new = not CustomUser.objects.filter(email__iexact=email).exists()

            if is_new:
                password = get_random_string(10)
                base_username = slugify(
                    f"{pdata['first_name']}.{pdata['last_name']}"
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
                    first_name=pdata['first_name'],
                    last_name=pdata['last_name'],
                )
                user.must_change_password = True
                if pdata.get('phone'):
                    user.phone = pdata['phone']
                if pdata.get('address'):
                    user.address_line1 = pdata['address']
                if pdata.get('city'):
                    user.city = pdata['city']
                if pdata.get('country'):
                    user.country = pdata['country']
                user.save()

                UserRole.objects.get_or_create(user=user, role=parent_role)
                credentials.append({
                    'username': username,
                    'email': email,
                    'password': password,
                    'first_name': pdata['first_name'],
                    'last_name': pdata['last_name'],
                    'children': ', '.join(c['student_name'] for c in pdata['children']),
                })
                counts['parents_created'] += 1
            else:
                user = CustomUser.objects.filter(email__iexact=email).first()
                password = None
                # Ensure parent role assigned
                UserRole.objects.get_or_create(user=user, role=parent_role)

            # Create ParentStudent links
            for child in pdata['children']:
                if child.get('at_max_parents'):
                    counts['links_skipped'] += 1
                    continue

                student_user = CustomUser.objects.get(id=child['student_id'])
                _, created = ParentStudent.objects.get_or_create(
                    parent=user, student=student_user, school=school,
                    defaults={
                        'relationship': child.get('relationship', ''),
                        'is_active': True,
                        'created_by': imported_by,
                    },
                )
                if created:
                    counts['links_created'] += 1
                else:
                    counts['links_skipped'] += 1

    return {
        'counts': counts,
        'credentials': credentials,
    }
