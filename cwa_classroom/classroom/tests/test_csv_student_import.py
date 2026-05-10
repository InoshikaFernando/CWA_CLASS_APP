"""Tests for CSV student bulk import — services, views, and permissions."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolTeacher, SchoolStudent, Department, DepartmentSubject,
    Subject, Level, ClassRoom, ClassStudent, Guardian, StudentGuardian,
    ParentStudent,
)
from classroom.import_services import (
    parse_csv_file, parse_upload_file, validate_and_preview, execute_import,
    _build_column_mapping, apply_preset, SOURCE_PRESETS,
)


class CSVImportTestBase(TestCase):
    """Shared fixtures."""

    @classmethod
    def setUpTestData(cls):
        cls.role_hoi, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        cls.role_teacher, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.role_student, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        cls.superuser = CustomUser.objects.create_superuser(
            'superadmin', 'wlhtestmails+super@gmail.com', 'password1!',
        )
        cls.hoi_user = CustomUser.objects.create_user(
            'hoi', 'wlhtestmails+hoi@gmail.com', 'password1!',
        )
        cls.hoi_user.roles.add(cls.role_hoi)

        cls.teacher_user = CustomUser.objects.create_user(
            'teacher', 'wlhtestmails+teacher@gmail.com', 'password1!',
        )
        cls.teacher_user.roles.add(cls.role_teacher)

        cls.student_user = CustomUser.objects.create_user(
            'student', 'wlhtestmails+student@gmail.com', 'password1!',
        )
        cls.student_user.roles.add(cls.role_student)

        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.superuser,
        )
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.hoi_user, defaults={'role': 'head_of_institute'})

        # A level for matching
        cls.level7, _ = Level.objects.get_or_create(
            level_number=7,
            defaults={'display_name': 'Year 7'},
        )

    SIMPLE_CSV = (
        b'first_name,last_name,email,department,subject,level,class_name,class_day\n'
        b'John,Smith,john@school.nz,Mathematics,Mathematics,Year 7,Year 7 Mon,Monday\n'
        b'Jane,Doe,jane@school.nz,Mathematics,Mathematics,Year 7,Year 7 Mon,Monday\n'
    )

    MULTI_CLASS_CSV = (
        b'first_name,last_name,email,department,subject,level,class_name,class_day\n'
        b'John,Smith,john@school.nz,Mathematics,Mathematics,Year 7,Year 7 Mon,Monday\n'
        b'John,Smith,john@school.nz,Mathematics,Mathematics,Year 7,Year 7 Wed,Wednesday\n'
    )

    GUARDIAN_CSV = (
        b'first_name,last_name,email,parent1_first_name,parent1_last_name,parent1_email,parent1_phone,parent1_relationship\n'
        b'John,Smith,john@school.nz,Mary,Smith,mary@parent.com,+6421111,Mother\n'
        b'Jane,Smith,jane@school.nz,Mary,Smith,mary@parent.com,+6421111,Mother\n'
    )


# ─────────────────────────────────────────────────────────────
# 1. parse_csv_file
# ─────────────────────────────────────────────────────────────

class ParseCSVTests(CSVImportTestBase):

    def test_valid_csv(self):
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        self.assertEqual(len(headers), 8)
        self.assertEqual(len(rows), 2)
        self.assertEqual(headers[0], 'first_name')

    def test_latin1_encoding(self):
        content = 'first_name,last_name,email\nJos\xe9,Garc\xeda,wlhtestmails+jose@gmail.com\n'.encode('latin-1')
        headers, rows = parse_csv_file(content)
        self.assertEqual(len(rows), 1)

    def test_empty_csv_raises(self):
        with self.assertRaises(ValueError):
            parse_csv_file(b'first_name,last_name,email\n')

    def test_header_only_raises(self):
        with self.assertRaises(ValueError):
            parse_csv_file(b'first_name\n')


# ─────────────────────────────────────────────────────────────
# 2. validate_and_preview
# ─────────────────────────────────────────────────────────────

class ValidateAndPreviewTests(CSVImportTestBase):

    def _mapping(self, headers):
        """Auto-map headers by position."""
        return {h: i for i, h in enumerate(headers)}

    def test_missing_required_field_error(self):
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        # Only map first_name, missing last_name and email
        mapping = {'first_name': 0}
        result = validate_and_preview(rows, mapping, self.school)
        self.assertTrue(any('Last Name' in e for e in result['errors']))

    def test_basic_preview(self):
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = self._mapping(headers)
        result = validate_and_preview(rows, mapping, self.school)
        self.assertEqual(len(result['students_new']), 2)
        self.assertEqual(len(result['classes_new']), 1)  # Year 7 Mon
        self.assertIn('Mathematics', result['departments_new'])

    def test_full_name_splits_into_first_last(self):
        """full_name column auto-splits into first + last name."""
        csv = (
            b'full_name,email\n'
            b'John Smith,wlhtestmails+john@gmail.com\n'
            b'Ridma Amreen Rahman,wlhtestmails+ridma@gmail.com\n'
            b'Madonna,wlhtestmails+madonna@gmail.com\n'
        )
        headers, rows = parse_csv_file(csv)
        mapping = {'full_name': 0, 'email': 1}
        result = validate_and_preview(rows, mapping, self.school)
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(len(result['students_new']), 3)

        names = {s['first_name']: s['last_name'] for s in result['students_new']}
        self.assertEqual(names['John'], 'Smith')
        self.assertEqual(names['Ridma'], 'Amreen Rahman')
        self.assertEqual(names['Madonna'], '')  # single name

    def test_full_name_not_required_when_first_last_mapped(self):
        """first_name + last_name still works without full_name."""
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = self._mapping(headers)
        result = validate_and_preview(rows, mapping, self.school)
        self.assertEqual(len(result['students_new']), 2)

    def test_student_deduplication(self):
        headers, rows = parse_csv_file(self.MULTI_CLASS_CSV)
        mapping = self._mapping(headers)
        result = validate_and_preview(rows, mapping, self.school)
        # John appears twice but should be deduped to 1 student
        self.assertEqual(len(result['students_new']), 1)
        # But enrolled in 2 classes
        self.assertEqual(len(result['students_new'][0]['classes']), 2)

    def test_existing_student_detected(self):
        # Pre-create John
        CustomUser.objects.create_user('john', 'john@school.nz', 'password1!')
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = self._mapping(headers)
        result = validate_and_preview(rows, mapping, self.school)
        self.assertEqual(len(result['students_existing']), 1)
        self.assertEqual(len(result['students_new']), 1)

    def test_guardian_dedup_across_siblings(self):
        headers, rows = parse_csv_file(self.GUARDIAN_CSV)
        mapping = self._mapping(headers)
        result = validate_and_preview(rows, mapping, self.school)
        # Both students share mary@parent.com
        self.assertEqual(len(result['guardians_new']), 1)
        self.assertEqual(result['guardians_new'][0]['email'], 'mary@parent.com')

    def test_missing_email_auto_generates(self):
        """When email is missing, it's auto-generated from student name."""
        csv = b'first_name,last_name\nJohn,Smith\n'
        headers, rows = parse_csv_file(csv)
        mapping = self._mapping(headers)
        result = validate_and_preview(rows, mapping, self.school)
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(len(result['students_new']), 1)
        self.assertIn('@student.local', result['students_new'][0]['email'])


# ─────────────────────────────────────────────────────────────
# 3. execute_import
# ─────────────────────────────────────────────────────────────

class ExecuteImportTests(CSVImportTestBase):

    def test_full_import(self):
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = {h: i for i, h in enumerate(headers)}
        preview = validate_and_preview(rows, mapping, self.school)
        results = execute_import(preview, self.school, self.hoi_user)

        self.assertEqual(results['counts']['students_created'], 2)
        self.assertEqual(results['counts']['classes_created'], 1)
        self.assertEqual(results['counts']['departments_created'], 1)
        self.assertEqual(len(results['credentials']), 2)

        # Verify DB state
        self.assertTrue(CustomUser.objects.filter(email='john@school.nz').exists())
        self.assertTrue(CustomUser.objects.filter(email='jane@school.nz').exists())
        john = CustomUser.objects.get(email='john@school.nz')
        self.assertTrue(SchoolStudent.objects.filter(student=john, school=self.school).exists())
        self.assertTrue(ClassStudent.objects.filter(student=john).exists())
        self.assertTrue(Department.objects.filter(school=self.school, name='Mathematics').exists())
        classroom = ClassRoom.objects.get(name='Year 7 Mon', school=self.school)
        self.assertEqual(classroom.day, 'monday')

    def test_multi_class_enrollment(self):
        headers, rows = parse_csv_file(self.MULTI_CLASS_CSV)
        mapping = {h: i for i, h in enumerate(headers)}
        preview = validate_and_preview(rows, mapping, self.school)
        results = execute_import(preview, self.school, self.hoi_user)

        self.assertEqual(results['counts']['students_created'], 1)
        self.assertEqual(results['counts']['classes_created'], 2)
        john = CustomUser.objects.get(email='john@school.nz')
        self.assertEqual(ClassStudent.objects.filter(student=john).count(), 2)

    def test_guardian_creation_and_linking(self):
        """
        CSV parent rows create a CustomUser + ParentStudent link per child
        (login-capable account), not a Guardian contact record. Guardian/
        StudentGuardian are intentionally not created by this importer —
        they duplicated rows in the admin Parents list.
        """
        headers, rows = parse_csv_file(self.GUARDIAN_CSV)
        mapping = {h: i for i, h in enumerate(headers)}
        preview = validate_and_preview(rows, mapping, self.school)
        results = execute_import(preview, self.school, self.hoi_user)

        # No Guardian contact record is created by the importer.
        self.assertEqual(results['counts']['guardians_created'], 0)
        self.assertFalse(
            Guardian.objects.filter(email='mary@parent.com', school=self.school).exists()
        )

        # A parent CustomUser was created and linked to both students.
        mary = CustomUser.objects.get(email='mary@parent.com')
        self.assertEqual(mary.first_name, 'Mary')
        self.assertEqual(
            ParentStudent.objects.filter(
                parent=mary, school=self.school, is_active=True,
            ).count(),
            2,
        )

    def test_credentials_contain_passwords(self):
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = {h: i for i, h in enumerate(headers)}
        preview = validate_and_preview(rows, mapping, self.school)
        results = execute_import(preview, self.school, self.hoi_user)

        for cred in results['credentials']:
            self.assertIn('password', cred)
            self.assertTrue(len(cred['password']) >= 10)
            # Verify the password actually works
            user = CustomUser.objects.get(email=cred['email'])
            self.assertTrue(user.check_password(cred['password']))

    def test_existing_student_not_duplicated(self):
        # Pre-create John
        john = CustomUser.objects.create_user(
            'john_existing', 'john@school.nz', 'oldpass',
            first_name='John', last_name='Smith',
        )
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = {h: i for i, h in enumerate(headers)}
        preview = validate_and_preview(rows, mapping, self.school)
        results = execute_import(preview, self.school, self.hoi_user)

        # Only Jane should be created
        self.assertEqual(results['counts']['students_created'], 1)
        # John should still be enrolled in class
        self.assertTrue(ClassStudent.objects.filter(student=john).exists())

    def test_unique_username_collision(self):
        # Pre-create a user with username 'john'
        CustomUser.objects.create_user('john', 'wlhtestmails+other@gmail.com', 'password1!')
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = {h: i for i, h in enumerate(headers)}
        preview = validate_and_preview(rows, mapping, self.school)
        results = execute_import(preview, self.school, self.hoi_user)

        # john@school.nz should get username 'john1' (collision avoidance)
        new_john = CustomUser.objects.get(email='john@school.nz')
        self.assertNotEqual(new_john.username, 'john')
        self.assertTrue(new_john.username.startswith('john'))

    def test_department_subject_link(self):
        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = {h: i for i, h in enumerate(headers)}
        preview = validate_and_preview(rows, mapping, self.school)
        execute_import(preview, self.school, self.hoi_user)

        dept = Department.objects.get(school=self.school, name='Mathematics')
        # Subject may be school-scoped or global depending on seed data
        subj = Subject.objects.filter(name='Mathematics').first()
        self.assertIsNotNone(subj)
        self.assertTrue(DepartmentSubject.objects.filter(
            department=dept, subject=subj,
        ).exists())


# ─────────────────────────────────────────────────────────────
# 4. View access tests
# ─────────────────────────────────────────────────────────────

class CSVImportViewAccessTests(CSVImportTestBase):

    def test_superuser_can_access_upload(self):
        self.client.login(username='superadmin', password='password1!')
        resp = self.client.get(reverse('student_csv_upload'))
        self.assertEqual(resp.status_code, 200)

    def test_hoi_can_access_upload(self):
        self.client.login(username='hoi', password='password1!')
        resp = self.client.get(reverse('student_csv_upload'))
        self.assertEqual(resp.status_code, 200)

    def test_teacher_cannot_access_upload(self):
        self.client.login(username='teacher', password='password1!')
        resp = self.client.get(reverse('student_csv_upload'))
        self.assertEqual(resp.status_code, 302)

    def test_student_cannot_access_upload(self):
        self.client.login(username='student', password='password1!')
        resp = self.client.get(reverse('student_csv_upload'))
        self.assertEqual(resp.status_code, 302)

    def test_credentials_empty_redirects(self):
        self.client.login(username='hoi', password='password1!')
        resp = self.client.get(reverse('student_csv_credentials'))
        self.assertEqual(resp.status_code, 302)


# ─────────────────────────────────────────────────────────────
# 5. End-to-end view test
# ─────────────────────────────────────────────────────────────

class CSVImportE2ETests(CSVImportTestBase):

    def test_upload_parses_and_shows_mapping(self):
        self.client.login(username='hoi', password='password1!')
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv_file = SimpleUploadedFile('students.csv', self.SIMPLE_CSV, content_type='text/csv')
        resp = self.client.post(reverse('student_csv_upload'), {'csv_file': csv_file})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Map Columns')
        self.assertContains(resp, 'first_name')

    def test_upload_with_preset_shows_banner(self):
        self.client.login(username='hoi', password='password1!')
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Use Teachworks Families-like headers
        tw_csv = (
            b'First Name,Last Name,Family First,Family Last,Family Email,Family phone\n'
            b'Ryan,Smith,Mary,Smith,mary@parent.com,+6421111\n'
        )
        csv_file = SimpleUploadedFile('students.csv', tw_csv, content_type='text/csv')
        resp = self.client.post(
            reverse('student_csv_upload'),
            {'csv_file': csv_file, 'source_preset': 'teachworks'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'auto-mapped')

    def test_upload_page_shows_presets(self):
        self.client.login(username='hoi', password='password1!')
        resp = self.client.get(reverse('student_csv_upload'))
        self.assertContains(resp, 'Teachworks')
        self.assertContains(resp, 'source_preset')


# ─────────────────────────────────────────────────────────────
# 6. Source presets
# ─────────────────────────────────────────────────────────────

class SourcePresetTests(CSVImportTestBase):

    TEACHWORKS_STUDENTS_HEADERS = [
        'Type', 'Student ID', 'Customer ID', 'First Name', 'Last Name',
        'Family First', 'Family Last', 'Email', 'Additional Email',
        'Mobile phone', 'Home phone', 'Family Email', 'Family Additional Email',
        'Family phone', 'Family Home Phone', 'Family Work Phone',
        'Address', 'Address Line 2', 'City', 'State', 'Zip Code', 'Country',
        'Time Zone', 'Birth Date', 'Start Date', 'School', 'Subjects', 'Grade',
        'Additional Info', 'Calendar Color', 'Billing Method', 'Student Cost',
        'Discount Rate', 'Cost Premium', 'Default Service', 'Default Location',
        'Status', 'Family Status', 'Teachers',
    ]

    TEACHWORKS_FAMILIES_HEADERS = [
        'ID', 'Title', 'First Name', 'Last Name', 'Children', 'Email',
        'Additional Email', 'Mobile Phone', 'Home Phone', 'Work Phone',
        'Address', 'Address 2', 'City', 'State', 'Zip', 'Country',
    ]

    def test_apply_teachworks_preset(self):
        mapping = apply_preset('teachworks', self.TEACHWORKS_STUDENTS_HEADERS)
        self.assertEqual(mapping['first_name'], 3)   # 'First Name'
        self.assertEqual(mapping['last_name'], 4)     # 'Last Name'
        self.assertEqual(mapping['date_of_birth'], 23)  # 'Birth Date'
        self.assertEqual(mapping['level'], 26)         # 'Subjects'
        self.assertEqual(mapping['class_name'], 34)    # 'Default Service'
        self.assertEqual(mapping['parent1_first_name'], 5)  # 'Family First'
        self.assertEqual(mapping['parent1_email'], 11)     # 'Family Email'

    def test_apply_unknown_preset_returns_empty(self):
        mapping = apply_preset('nonexistent', ['A', 'B', 'C'])
        self.assertEqual(mapping, {})

    def test_preset_case_insensitive(self):
        headers = ['FIRST NAME', 'last name', 'FAMILY EMAIL', 'birth date']
        mapping = apply_preset('teachworks', headers)
        self.assertEqual(mapping['first_name'], 0)
        self.assertEqual(mapping['last_name'], 1)
        self.assertEqual(mapping['date_of_birth'], 3)

    def test_children_column_expands_rows(self):
        """Families CSV with children column expands into student rows."""
        from classroom.import_services import _expand_children_rows, _split_child_name

        # Test name splitting
        self.assertEqual(_split_child_name('Ryan Smith'), ('Ryan', 'Smith'))
        self.assertEqual(_split_child_name('Ridma Amreen Rahman'), ('Ridma', 'Amreen Rahman'))
        self.assertEqual(_split_child_name('Ryan'), ('Ryan', ''))

        # Test row expansion
        rows = [
            ['', '', 'Parent', 'Smith', 'Ryan Smith, Jane Smith', 'wlhtestmails+parent@gmail.com'],
        ]
        expanded = _expand_children_rows(rows, {'children': 4})
        self.assertEqual(len(expanded), 2)
        # Extra columns appended for child first/last
        self.assertEqual(expanded[0][-2], 'Ryan')
        self.assertEqual(expanded[0][-1], 'Smith')
        self.assertEqual(expanded[1][-2], 'Jane')
        self.assertEqual(expanded[1][-1], 'Smith')

    def test_source_presets_registry(self):
        self.assertIn('teachworks', SOURCE_PRESETS)
        self.assertIn('name', SOURCE_PRESETS['teachworks'])
        self.assertIn('mapping', SOURCE_PRESETS['teachworks'])


class ParseUploadFileTests(CSVImportTestBase):

    def test_csv_by_extension(self):
        headers, rows = parse_upload_file(self.SIMPLE_CSV, 'students.csv')
        self.assertEqual(len(rows), 2)

    def test_xlsx_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            parse_upload_file(b'fake', 'students.xlsx')
        self.assertIn('XLSX', str(ctx.exception))


# ─────────────────────────────────────────────────────────────
# Smart structure mapping tests
# ─────────────────────────────────────────────────────────────

class ExtractCSVStructureTests(CSVImportTestBase):

    def test_extracts_unique_subjects_levels_classes(self):
        from classroom.import_services import extract_csv_structure
        csv = (
            b'first_name,last_name,email,subject,level,class_name\n'
            b'John,Smith,wlhtestmails+john@gmail.com,Maths,Year 7,7A-Mon\n'
            b'Jane,Doe,wlhtestmails+jane@gmail.com,Maths,Year 8,8A-Mon\n'
            b'Bob,Lee,wlhtestmails+bob@gmail.com,Science,Year 7,7B-Mon\n'
        )
        headers, rows = parse_csv_file(csv)
        mapping = {'subject': 3, 'level': 4, 'class_name': 5}
        result = extract_csv_structure(rows, mapping)
        self.assertEqual(result['csv_subjects'], ['Maths', 'Science'])
        self.assertEqual(result['csv_levels'], ['Year 7', 'Year 8'])
        self.assertEqual(result['csv_classes'], ['7A-Mon', '7B-Mon', '8A-Mon'])

    def test_empty_csv_returns_empty_lists(self):
        from classroom.import_services import extract_csv_structure
        csv = b'first_name,last_name,email\nJohn,Smith,wlhtestmails+john@gmail.com\n'
        headers, rows = parse_csv_file(csv)
        result = extract_csv_structure(rows, {'first_name': 0})
        self.assertEqual(result['csv_subjects'], [])
        self.assertEqual(result['csv_levels'], [])
        self.assertEqual(result['csv_classes'], [])


class SmartMappingContextTests(CSVImportTestBase):

    def setUp(self):
        self.dept = Department.objects.create(
            school=self.school, name='Science', slug='science',
        )

    def test_neither_scenario(self):
        from classroom.import_services import build_smart_mapping_context
        ctx = build_smart_mapping_context(
            {'csv_subjects': [], 'csv_levels': [], 'csv_classes': []},
            self.dept,
        )
        self.assertEqual(ctx['subject_scenario'], 'neither')
        self.assertEqual(ctx['level_scenario'], 'neither')
        self.assertEqual(ctx['class_scenario'], 'neither')

    def test_csv_only_scenario(self):
        from classroom.import_services import build_smart_mapping_context
        ctx = build_smart_mapping_context(
            {'csv_subjects': ['Physics'], 'csv_levels': ['Year 9'], 'csv_classes': ['9A']},
            self.dept,
        )
        self.assertEqual(ctx['subject_scenario'], 'csv_only')
        self.assertEqual(ctx['level_scenario'], 'csv_only')
        self.assertEqual(ctx['class_scenario'], 'csv_only')

    def test_both_scenario(self):
        from classroom.import_services import build_smart_mapping_context
        subj = Subject.objects.create(
            name='Physics', slug='physics', school=self.school,
        )
        DepartmentSubject.objects.create(department=self.dept, subject=subj)

        ctx = build_smart_mapping_context(
            {'csv_subjects': ['Phys'], 'csv_levels': [], 'csv_classes': []},
            self.dept,
        )
        self.assertEqual(ctx['subject_scenario'], 'both')
        self.assertEqual(len(ctx['system_subjects']), 1)
        self.assertEqual(ctx['system_subjects'][0]['name'], 'Physics')


class StructureMappedImportTests(CSVImportTestBase):

    def test_import_with_subject_mapping(self):
        """Subjects from CSV mapped to existing system subject."""
        from classroom.import_services import apply_structure_mapping

        dept = Department.objects.create(
            school=self.school, name='Maths Dept', slug='maths-dept',
        )
        subj = Subject.objects.create(
            name='Mathematics', slug='maths-local', school=self.school,
        )
        DepartmentSubject.objects.create(department=dept, subject=subj)

        headers, rows = parse_csv_file(self.SIMPLE_CSV)
        mapping = _build_column_mapping({
            'col_first_name': '0', 'col_last_name': '1', 'col_email': '2',
            'col_department': '3', 'col_subject': '4', 'col_level': '5',
            'col_class_name': '6', 'col_class_day': '7',
        })
        preview = validate_and_preview(rows, mapping, self.school)

        structure_mapping = {
            'department_id': dept.id,
            'subject_map': {'Mathematics': str(subj.id)},
            'level_map': {'Year 7': str(self.level7.id)},
            'class_map': {'Year 7 Mon': 'create'},
            'dummy_subject': False,
            'dummy_level': False,
            'dummy_class': False,
        }
        apply_structure_mapping(preview, structure_mapping, dept)
        result = execute_import(preview, self.school, self.superuser)

        self.assertGreater(result['counts']['students_created'], 0)
        self.assertEqual(result['counts']['classes_created'], 1)
        # The class should be linked to the target department
        cr = ClassRoom.objects.get(name='Year 7 Mon', school=self.school)
        self.assertEqual(cr.department, dept)

    def test_import_with_dummy_entities(self):
        """When neither CSV nor system has structure, dummies are created."""
        from classroom.import_services import apply_structure_mapping

        dept = Department.objects.create(
            school=self.school, name='Empty Dept', slug='empty-dept',
        )

        # CSV with no subject/level/class columns
        csv = b'first_name,last_name,email\nAlice,Wong,wlhtestmails+alice@gmail.com\n'
        headers, rows = parse_csv_file(csv)
        mapping = _build_column_mapping({
            'col_first_name': '0', 'col_last_name': '1', 'col_email': '2',
        })
        preview = validate_and_preview(rows, mapping, self.school)

        structure_mapping = {
            'department_id': dept.id,
            'subject_map': {},
            'level_map': {},
            'class_map': {},
            'dummy_subject': True,
            'dummy_level': True,
            'dummy_class': True,
        }
        apply_structure_mapping(preview, structure_mapping, dept)
        result = execute_import(preview, self.school, self.superuser)

        self.assertEqual(result['counts']['students_created'], 1)
        self.assertEqual(result['counts']['classes_created'], 1)
        self.assertEqual(result['counts']['subjects_created'], 1)
        self.assertEqual(result['counts']['levels_created'], 1)

        # Student should be enrolled in the dummy class
        alice = CustomUser.objects.get(email='wlhtestmails+alice@gmail.com')
        self.assertTrue(ClassStudent.objects.filter(student=alice).exists())
        dummy_class = ClassStudent.objects.get(student=alice).classroom
        self.assertEqual(dummy_class.department, dept)
