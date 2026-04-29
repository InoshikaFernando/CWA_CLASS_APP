# Unified Question Upload System - Design Document

**Date**: April 28, 2026  
**Version**: 1.0  
**Status**: Design Phase

---

## 1. System Overview

A unified, multi-format question upload system with role-based visibility control. Supports JSON, CSV, and Excel formats for creating questions globally (Super User) or locally (Institute Admin, Class Teachers).

---

## 2. Existing Infrastructure

### 2.1 Question Models

#### Maths (maths/models.py)
- `Question`: Full ORM model with fields for scope control
  - `school` (FK): Null = global, Set = local to school
  - `department` (FK): Null = not scoped, Set = visible to department only
  - `classroom` (FK): Null = not scoped, Set = visible to class only
  - `question_text`, `question_type`, `difficulty`, `level`, `topic`
  - `Answer`: Related model for MCQ/TF options

#### Coding (coding/models.py)
- `CodingExercise`: Coding question/exercise model
  - **MISSING**: school, department, classroom fields (need to add)
  - `topic_level` (FK): Topic + Level combination
  - `question_type`: WRITE_CODE, MULTIPLE_CHOICE, TRUE_FALSE, SHORT_ANSWER, FILL_BLANK
  - `CodingAnswer`: Related model for MCQ/TF options

### 2.2 User Roles (from Django auth)
- **Superuser**: `user.is_superuser == True`
- **Institute Admin**: Has `school` attribute + staff status
- **Class Teacher**: Has `school` + `classroom` attributes + staff status

---

## 3. Architecture Design

### 3.1 Database Schema Updates

#### Migrate CodingExercise to Support Visibility
Add to `coding/migrations/`:
```python
# Add school, department, classroom FKs to CodingExercise
school = models.ForeignKey('classroom.School', on_delete=models.CASCADE, null=True, blank=True)
department = models.ForeignKey('classroom.Department', on_delete=models.CASCADE, null=True, blank=True)
classroom = models.ForeignKey('classroom.ClassRoom', on_delete=models.CASCADE, null=True, blank=True)
```

### 3.2 File Parsing Utilities

**Location**: `brainbuzz/upload_parsers.py` (shared utility)

```python
class BaseQuestionParser:
    """Abstract base for question file parsers."""
    def parse(self, file_obj) -> List[Dict]:
        """Returns list of question dicts."""
        pass
    
    def validate_question(self, q_dict) -> Tuple[bool, List[str]]:
        """Validate question structure. Returns (is_valid, errors)."""
        pass

class JSONQuestionParser(BaseQuestionParser):
    """Parses JSON question files."""
    def parse(self, file_obj) -> List[Dict]: ...
    def validate_question(self, q_dict): ...

class CSVQuestionParser(BaseQuestionParser):
    """Parses CSV question files."""
    # Headers: topic, level, question_text, question_type, difficulty, answer1, is_correct1, ...
    def parse(self, file_obj) -> List[Dict]: ...

class ExcelQuestionParser(BaseQuestionParser):
    """Parses Excel question files."""
    # Same structure as CSV but from Excel sheet
    def parse(self, file_obj) -> List[Dict]: ...
```

### 3.3 Role-Based Permission Helpers

**Location**: `brainbuzz/permissions.py`

```python
def get_user_role(user) -> str:
    """Return 'superuser', 'admin', or 'teacher'."""
    if user.is_superuser:
        return 'superuser'
    if user.school and user.is_staff:
        return 'admin' if is_institute_admin(user) else 'teacher'
    return 'guest'

def auto_scope_question(question_dict, user, subject_type='maths'):
    """Automatically set school/department/classroom based on role."""
    role = get_user_role(user)
    
    if role == 'superuser':
        question_dict['school'] = None  # Global
        question_dict['department'] = None
        question_dict['classroom'] = None
    
    elif role == 'admin':
        question_dict['school'] = user.school
        question_dict['department'] = None  # Allow school-wide visibility
        question_dict['classroom'] = None
    
    elif role == 'teacher':
        question_dict['school'] = user.school
        question_dict['department'] = None
        question_dict['classroom'] = user.classroom
    
    return question_dict

def can_upload_questions(user) -> bool:
    """Check if user can upload questions."""
    return user.is_authenticated and (
        user.is_superuser or 
        (user.is_staff and user.school)
    )

def can_see_question(question, user) -> bool:
    """Check if user can view/use a question."""
    # Global questions visible to all
    if question.school is None:
        return True
    
    # Local questions visible only within same school/scope
    if question.school != user.school:
        return False
    
    # If department-scoped, check department
    if question.department and question.department != user.department:
        return False
    
    # If class-scoped, check class
    if question.classroom and question.classroom != user.classroom:
        return False
    
    return True
```

### 3.4 Upload Service

**Location**: `brainbuzz/upload_service.py`

```python
class QuestionUploadService:
    """Handles question import workflow: parse → validate → save."""
    
    def __init__(self, user, subject_type='maths'):
        self.user = user
        self.subject_type = subject_type
        self.parser = None
        self.errors = []
        self.created_count = 0
        self.skipped_count = 0
    
    def upload_file(self, file_obj, file_format) -> Dict:
        """Main upload entry point. Returns {status, created, skipped, errors}."""
        try:
            # Select parser based on file_format
            if file_format == 'json':
                self.parser = JSONQuestionParser()
            elif file_format == 'csv':
                self.parser = CSVQuestionParser()
            elif file_format == 'excel':
                self.parser = ExcelQuestionParser()
            else:
                self.errors.append(f"Unsupported format: {file_format}")
                return self._result()
            
            # Parse file
            questions = self.parser.parse(file_obj)
            
            # Validate and save each question
            for q_dict in questions:
                if self._process_question(q_dict):
                    self.created_count += 1
                else:
                    self.skipped_count += 1
            
            return self._result()
        
        except Exception as e:
            self.errors.append(f"Upload failed: {str(e)}")
            return self._result()
    
    def _process_question(self, q_dict) -> bool:
        """Validate and save a single question. Returns True if saved."""
        # Validate structure
        is_valid, errors = self.parser.validate_question(q_dict)
        if not is_valid:
            self.errors.extend(errors)
            return False
        
        # Auto-scope based on user role
        q_dict = auto_scope_question(q_dict, self.user, self.subject_type)
        
        # Check for duplicates
        if self._duplicate_exists(q_dict):
            self.errors.append(f"Duplicate question: {q_dict['question_text'][:50]}...")
            return False
        
        # Save to database
        try:
            self._save_question(q_dict)
            return True
        except Exception as e:
            self.errors.append(f"Save failed: {str(e)}")
            return False
    
    def _duplicate_exists(self, q_dict) -> bool:
        """Check if question already exists."""
        if self.subject_type == 'maths':
            from maths.models import Question
            return Question.objects.filter(
                question_text=q_dict['question_text'],
                topic__id=q_dict['topic_id'],
                level__id=q_dict['level_id'],
            ).exists()
        elif self.subject_type == 'coding':
            from coding.models import CodingExercise
            return CodingExercise.objects.filter(
                title=q_dict['title'],
                topic_level__id=q_dict['topic_level_id'],
            ).exists()
        return False
    
    def _save_question(self, q_dict):
        """Save question to database."""
        if self.subject_type == 'maths':
            from maths.models import Question, Answer
            question = Question.objects.create(**q_dict)
            # Create answers if MCQ/TF
            for answer_dict in q_dict.get('answers', []):
                Answer.objects.create(question=question, **answer_dict)
        elif self.subject_type == 'coding':
            from coding.models import CodingExercise, CodingAnswer
            exercise = CodingExercise.objects.create(**q_dict)
            # Create answers if MCQ/TF
            for answer_dict in q_dict.get('answers', []):
                CodingAnswer.objects.create(exercise=exercise, **answer_dict)
    
    def _result(self) -> Dict:
        return {
            'status': 'error' if self.errors else 'success',
            'created': self.created_count,
            'skipped': self.skipped_count,
            'errors': self.errors,
        }
```

### 3.5 Views & Forms

**Location**: `brainbuzz/views_upload.py`

```python
@login_required
def upload_questions(request):
    """Unified question upload interface."""
    if not can_upload_questions(request.user):
        return HttpResponse("Permission denied", status=403)
    
    if request.method == 'POST':
        form = QuestionUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file_obj = request.FILES['file']
            file_format = form.cleaned_data['format']
            subject = form.cleaned_data['subject']
            
            service = QuestionUploadService(request.user, subject)
            result = service.upload_file(file_obj, file_format)
            
            return render(request, 'brainbuzz/upload_results.html', {
                'result': result,
                'user_role': get_user_role(request.user),
            })
    else:
        form = QuestionUploadForm()
    
    return render(request, 'brainbuzz/upload_form.html', {
        'form': form,
        'user_role': get_user_role(request.user),
    })
```

**Location**: `brainbuzz/forms.py`

```python
class QuestionUploadForm(forms.Form):
    FILE_FORMAT_CHOICES = [
        ('json', 'JSON'),
        ('csv', 'CSV'),
        ('excel', 'Excel'),
    ]
    SUBJECT_CHOICES = [
        ('maths', 'Mathematics'),
        ('coding', 'Coding'),
    ]
    
    file = forms.FileField(
        label='Upload File',
        help_text='JSON, CSV, or Excel file',
        required=True,
    )
    format = forms.ChoiceField(
        choices=FILE_FORMAT_CHOICES,
        help_text='File format',
    )
    subject = forms.ChoiceField(
        choices=SUBJECT_CHOICES,
        help_text='Subject area',
    )
```

### 3.6 Templates

**Location**: `templates/brainbuzz/upload_form.html`

```html
{% extends "base.html" %}
{% block title %}Upload Questions{% endblock %}

{% block content %}
<div class="max-w-2xl mx-auto py-8 px-4">
  <h1 class="text-3xl font-bold mb-6">Upload Questions</h1>
  
  {% if user.is_superuser %}
  <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
    <p class="text-sm text-blue-800">
      <strong>Super User Mode:</strong> Uploaded questions will be visible globally to all institutes.
    </p>
  </div>
  {% elif user.is_staff %}
  <div class="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6">
    <p class="text-sm text-amber-800">
      <strong>Institute Admin:</strong> Uploaded questions will be visible only to your institute.
    </p>
  </div>
  {% endif %}
  
  <form method="post" enctype="multipart/form-data" class="bg-white border border-gray-200 rounded-lg p-6 space-y-6">
    {% csrf_token %}
    
    <div>
      <label class="block text-sm font-semibold text-gray-700 mb-2">Subject</label>
      {{ form.subject }}
    </div>
    
    <div>
      <label class="block text-sm font-semibold text-gray-700 mb-2">File Format</label>
      {{ form.format }}
    </div>
    
    <div>
      <label class="block text-sm font-semibold text-gray-700 mb-2">File</label>
      {{ form.file }}
      <p class="text-xs text-gray-500 mt-1">Max 10MB. Supported: JSON, CSV, Excel</p>
    </div>
    
    <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 rounded-lg">
      Upload Questions
    </button>
  </form>
</div>
{% endblock %}
```

---

## 4. API Endpoints

### 4.1 Question Selection API

**Route**: `/api/brainbuzz/questions/list/`

**Request**:
```json
{
  "subject": "maths",
  "topic_id": 5,
  "level_id": 3,
  "question_type": "multiple_choice"
}
```

**Response**:
```json
{
  "status": "success",
  "questions": [
    {
      "id": 123,
      "text": "What is 2+2?",
      "type": "multiple_choice",
      "answers": [...]
    }
  ],
  "total": 15
}
```

**Permission**: Authenticated users see only questions in their scope (global + their school/department)

---

## 5. Visibility Control Implementation

### 5.1 Query Filtering

All question queries must filter by visibility:

```python
# In views, managers, and APIs
def get_visible_questions(user, subject='maths'):
    """Get questions visible to user."""
    if subject == 'maths':
        from maths.models import Question
        qs = Question.objects.all()
    else:
        from coding.models import CodingExercise
        qs = CodingExercise.objects.all()
    
    # Global questions always visible
    global_filter = Q(school__isnull=True)
    
    # Local questions only if same school
    if hasattr(user, 'school') and user.school:
        local_filter = Q(school=user.school)
        
        # If institute admin, see everything in school
        # If teacher, respect department/classroom scope
        if not is_institute_admin(user):
            if user.classroom:
                local_filter &= Q(classroom__isnull=True) | Q(classroom=user.classroom)
            if user.department:
                local_filter &= Q(department__isnull=True) | Q(department=user.department)
    else:
        local_filter = Q()  # Can only see global
    
    return qs.filter(global_filter | local_filter)
```

---

## 6. Migration Path

### Phase 1: Foundation (Week 1)
- [ ] Create Coding Exercise visibility fields migration
- [ ] Create upload parsers (JSON, CSV, Excel)
- [ ] Create permissions and scoping utilities
- [ ] Unit tests for parsers and permissions

### Phase 2: Upload Feature (Week 2)
- [ ] Create QuestionUploadService
- [ ] Create upload views and forms
- [ ] Create upload templates
- [ ] Integration tests

### Phase 3: Question Selection & APIs (Week 3)
- [ ] Create question list API with visibility filtering
- [ ] Create question selection UI
- [ ] API tests for visibility control
- [ ] End-to-end tests with different user roles

### Phase 4: Polish & Documentation (Week 4)
- [ ] Error handling and user feedback
- [ ] Performance optimization
- [ ] Admin interface enhancements
- [ ] User documentation

---

## 7. Testing Strategy

### Unit Tests
- Parser validation (JSON, CSV, Excel)
- Permission checking functions
- Duplicate detection
- Scope assignment

### Integration Tests
- Upload flow for each user role
- Visibility filtering across queries
- Question reuse within scopes
- Error handling and recovery

### E2E Tests
- Super User uploads global questions
- Institute Admin uploads local questions
- Class Teacher uploads questions
- Question selection and visibility checks

---

## 8. Security Considerations

1. **File Upload Security**
   - Validate file size (max 10MB)
   - Validate file type
   - Scan for malicious content
   - Store outside webroot

2. **Permission Checks**
   - Check can_upload_questions() before allowing upload
   - Check can_see_question() before returning question data
   - Enforce at database level with filters

3. **SQL Injection Prevention**
   - Use Django ORM exclusively
   - Never build queries with string concatenation

4. **Data Isolation**
   - Ensure institute data never leaks to other institutes
   - Use school/department/classroom FKs as isolation boundaries

---

## 9. File Format Specifications

### JSON Format
```json
{
  "subject": "maths",
  "topic": "Fractions",
  "level": 5,
  "questions": [
    {
      "question_text": "What is 1/2 + 1/4?",
      "question_type": "multiple_choice",
      "difficulty": 2,
      "points": 1,
      "explanation": "1/2 = 2/4, so 2/4 + 1/4 = 3/4",
      "answers": [
        {"text": "3/4", "is_correct": true, "order": 1},
        {"text": "2/4", "is_correct": false, "order": 2},
        {"text": "1/4", "is_correct": false, "order": 3}
      ]
    }
  ]
}
```

### CSV Format
```csv
topic,level,question_text,question_type,difficulty,answer1,is_correct1,answer2,is_correct2,answer3,is_correct3,answer4,is_correct4
Fractions,5,"What is 1/2 + 1/4?",multiple_choice,2,3/4,true,2/4,false,1/4,false,2/3,false
```

### Excel Format
Same as CSV, with headers in first row.

---

## 10. Success Criteria

- [x] Design document complete
- [ ] CodingExercise visibility fields added
- [ ] All parsers working for JSON, CSV, Excel
- [ ] Permission system enforced
- [ ] Upload feature fully functional
- [ ] API with visibility filtering
- [ ] 95%+ test coverage for new code
- [ ] No breaking changes to existing features
- [ ] Documentation complete
- [ ] User acceptance testing passed

---

*End of Design Document*
