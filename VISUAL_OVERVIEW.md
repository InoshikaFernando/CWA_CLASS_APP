# Visual Overview: BrainBuzz Live Quiz System

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        BRAINBUZZ LIVE QUIZ SYSTEM                        │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐   │
│   │  Quiz Builder│   │  Live Session│   │   Question Upload         │   │
│   │  (Teacher)   │   │  (Real-Time) │   │   (Admin / Teacher)       │   │
│   └──────┬───────┘   └──────┬───────┘   └──────────────────────────┘   │
│          │                  │                          │                 │
│          ▼                  ▼                          ▼                 │
│   ┌──────────────────────────────────────────────────────────────┐      │
│   │                    QUESTION SOURCES                          │      │
│   │  ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐  │      │
│   │  │ maths.Question│  │coding.Coding │  │ BrainBuzzQuiz    │  │      │
│   │  │ (global/scoped│  │Exercise      │  │ (custom teacher  │  │      │
│   │  │  by role)     │  │ (global/     │  │  quiz)           │  │      │
│   │  │               │  │  scoped)     │  │                  │  │      │
│   │  └───────────────┘  └──────────────┘  └──────────────────┘  │      │
│   └──────────────────────────────────────────────────────────────┘      │
│                                  │                                       │
│                     SNAPSHOT AT SESSION CREATE                           │
│                                  │                                       │
│                                  ▼                                       │
│   ┌──────────────────────────────────────────────────────────────┐      │
│   │  BrainBuzzSession  +  BrainBuzzSessionQuestion (denormalized)│      │
│   └──────────────────────────────────────────────────────────────┘      │
│                                  │                                       │
│              ┌───────────────────┼───────────────────┐                  │
│              ▼                   ▼                   ▼                  │
│   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐       │
│   │ Teacher Views    │ │ Student Views    │ │ JSON API         │       │
│   │ lobby/play/end   │ │ join/play        │ │ state/submit/    │       │
│   └──────────────────┘ └──────────────────┘ │ leaderboard      │       │
│                                              └──────────────────┘       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Session Lifecycle

```
Teacher creates session
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  create_session  (POST /brainbuzz/create/)                │
│  Picks: subject → topic/level → question count           │
│  Snapshots questions into BrainBuzzSessionQuestion        │
│  Generates 6-char join code                              │
└────────────────────┬──────────────────────────────────────┘
                     │
                     ▼
             STATUS: lobby
┌───────────────────────────────────────────────────────────┐
│  teacher_lobby  (/session/<code>/lobby/)                  │
│  Displays QR code + join URL                             │
│  Students join via api_join → nickname assigned           │
└────────────────────┬──────────────────────────────────────┘
                     │  Teacher presses START
                     ▼
             STATUS: active
┌───────────────────────────────────────────────────────────┐
│  teacher_ingame  (/session/<code>/play/)                  │
│  teacher_action → start / reveal / next / end             │
│  Students poll api_session_state (versioned 304)          │
│  Students submit via api_submit → points awarded          │
└────────────────────┬──────────────────────────────────────┘
                     │  After each question
                     ▼
             STATUS: reveal
┌───────────────────────────────────────────────────────────┐
│  Answer distribution shown (per-option counts / correct%) │
│  teacher_action → next advances to next question          │
└────────────────────┬──────────────────────────────────────┘
                     │  After last question → end
                     ▼
             STATUS: finished
┌───────────────────────────────────────────────────────────┐
│  teacher_end  (/session/<code>/end/)                      │
│  Final leaderboard: rank / score / correct / avg time     │
│  export_csv → download results                            │
│  repeat_session → create fresh session, same config       │
└───────────────────────────────────────────────────────────┘
```

---

## Data Models

```
BrainBuzzSession
├── code           (6-char unique join code)
├── host           → User (teacher)
├── subject        → classroom.Subject
├── status         (lobby | active | reveal | between | finished | cancelled)
├── current_index  (0-based question position)
├── state_version  (increments on every state change → drives 304 caching)
├── question_deadline
├── time_per_question_sec
└── config_json    (for repeat_session)

BrainBuzzSessionQuestion  ← denormalized snapshot
├── session        → BrainBuzzSession
├── order
├── question_text
├── question_type  (mcq | tf | short | fill_blank)
├── options_json   [{label, text, is_correct}, …]
├── correct_short_answer
├── explanation
├── points_base    (default 1000)
└── source_model / source_id  (tracks origin)

BrainBuzzParticipant
├── session        → BrainBuzzSession
├── student        → User (nullable — anonymous allowed)
├── nickname       (unique within session)
├── score
└── last_correct_time  (tie-breaking)

BrainBuzzAnswer
├── participant    → BrainBuzzParticipant
├── session_question → BrainBuzzSessionQuestion  [unique_together]
├── selected_option_label  (MCQ/TF)
├── short_answer_text      (SA/FB)
├── submitted_at
├── time_taken_ms
├── points_awarded
└── is_correct

BrainBuzzQuiz  (custom teacher-built quiz)
├── title
├── subject        → classroom.Subject (nullable)
├── created_by     → User
└── is_draft

BrainBuzzQuizQuestion
├── quiz           → BrainBuzzQuiz
├── question_text
├── question_type  (mcq | tf | short | fill_blank)
├── time_limit     (seconds, default 20)
├── order
└── correct_short_answer (nullable)

BrainBuzzQuizOption
├── question       → BrainBuzzQuizQuestion
├── option_text
├── is_correct
└── order
```

---

## Question Sources & Snapshotting

```
Session Create
      │
      ├── subject = maths
      │     └── _snapshot_maths_questions(session, topic_id, level_id, count)
      │           maths.Question → filter MCQ/TF/SA/FB → random sample
      │           → BrainBuzzSessionQuestion (denormalized copy)
      │
      ├── subject = coding
      │     └── _snapshot_coding_questions(session, topic_level_id, count)
      │           coding.CodingExercise → filter MCQ/TF/SA/FB → random sample
      │           → BrainBuzzSessionQuestion
      │
      └── subject = custom quiz
            └── _snapshot_quiz_questions(session, quiz)
                  BrainBuzzQuizQuestion + BrainBuzzQuizOption
                  → BrainBuzzSessionQuestion
```

---

## Real-Time Polling (Versioned State)

```
Teacher performs action
    │
    ├── api_teacher_action (POST)
    │     Actions: start | reveal | next | end
    │     ├── start  → status=active, set deadline, bump version
    │     ├── reveal → status=reveal, bump version
    │     ├── next   → advance current_index → active, bump version
    │     └── end    → status=finished, bump version
    │
    └── session.bump_version() → state_version += 1

Student polls state
    │
    └── api_session_state (GET)
          If-None-Match header carries version etag
          ├── version unchanged → 304 Not Modified (no body)
          └── version changed   → 200 with full payload:
                {
                  status, current_index,
                  question: {text, type, options, deadline},
                  participants: [{nickname, score}, …],
                  answers_received: N,
                  answer_distribution: {…}   ← reveal phase only
                }
```

---

## Scoring Formula

```
Student submits answer
    │
    ├── Timing check: submitted_at ≤ question_deadline + 500ms grace
    │
    ├── Correctness check:
    │     MCQ/TF → exact option_label match (case-insensitive)
    │     SA/FB  → regex / exact match on correct_short_answer
    │
    └── Points (Kahoot formula):
          if correct:
            ratio = max(0, time_remaining / time_limit)
            points = int(points_base × (0.5 + 0.5 × ratio))
          else:
            points = 0

          participant.score += points
          participant.last_correct_time = now  (tie-breaking)
```

---

## Quiz Builder Flow

```
Teacher
  │
  ├─ GET  /brainbuzz/quizzes/            → list own quizzes
  ├─ POST /brainbuzz/quizzes/create/     → create BrainBuzzQuiz (draft)
  │
  └─ /brainbuzz/quizzes/<id>/build/      → interactive quiz builder UI
        │
        ├─ POST   api/quizzes/<id>/questions/          → add question + options
        ├─ PUT    api/quizzes/<id>/questions/<q_id>/   → edit question
        ├─ DELETE api/quizzes/<id>/questions/<q_id>/   → remove + re-number
        ├─ POST   api/quizzes/<id>/reorder/            → reorder questions
        └─ POST   api/quizzes/<id>/meta/               → update title/subject
  │
  ├─ POST /brainbuzz/quizzes/<id>/publish/
  │     Validates: ≥1 question, all MCQ/TF have ≥1 correct option
  │     Sets is_draft = False
  │
  └─ POST /brainbuzz/quizzes/<id>/launch/
        Snapshots quiz → BrainBuzzSession
        Redirects to teacher_lobby
```

---

## Question Upload Pipeline

```
User selects subject + file format + file
    │
    └─ POST /brainbuzz/upload/
          │
          ▼
    QuestionUploadService.upload_file()
          │
          ├─ 1. Permission check  (can_upload_questions)
          │
          ├─ 2. Parse file
          │     ├── JSON   → JSONQuestionParser
          │     ├── CSV    → CSVQuestionParser
          │     └── Excel  → ExcelQuestionParser (openpyxl)
          │           ↓
          │     list of question dicts
          │     {topic_name, level_number, question_text,
          │      question_type, difficulty, points,
          │      answers: [{text, is_correct, order}],
          │      correct_short_answer}
          │
          ├─ 3. For each question:
          │     a. auto_scope_question  → set school/dept/classroom from role
          │     b. _resolve_ids        → topic_name → topic_id
          │                               level_number → level_id
          │     c. _duplicate_exists   → skip if already in DB (same scope)
          │     d. _save_question      → INSERT Question + Answer rows
          │
          └─ 4. Return result dict
                {status, created, skipped, errors, warnings, timestamp}

Sample Templates (GET /brainbuzz/upload/sample/<format>/)
    ├── json   → sample_maths_questions.json
    ├── csv    → sample_maths_questions.csv
    └── excel  → sample_maths_questions.xlsx
    (Regenerate with: python manage.py create_sample_templates)
```

---

## Permission & Scoping Model

```
Role Detection  (get_user_role)
    │
    ├── is_superuser                      → 'superuser'
    ├── is_staff OR Role model match
    │     Admin roles: admin, institute_owner, head_of_institute,
    │                  head_of_department, senior_teacher
    │     Teacher roles: teacher, junior_teacher
    │   + school assigned via SchoolTeacher M2M
    │     ├── has classroom               → 'teacher'
    │     └── no classroom               → 'admin'
    └── otherwise                         → 'guest'

Question Scoping  (auto_scope_question)
    ├── superuser → school=NULL, dept=NULL, classroom=NULL  (global)
    ├── admin     → school=user_school, dept=NULL, classroom=NULL
    └── teacher   → school=user_school, dept=NULL, classroom=user_classroom

Visibility  (VisibleQuestionsQuerySet.visible_to)
    ├── superuser                   → all questions
    ├── authenticated + no school  → global only  (school IS NULL)
    └── authenticated + school     → global OR (school match
                                               + dept match if set
                                               + classroom match if set)

Upload Permission  (can_upload_questions)
    Allowed: superuser, admin, teacher
    Denied:  guest
```

---

## URL Map Summary

```
/brainbuzz/
├── create/                         ← teacher creates session
├── session/<code>/
│   ├── lobby/                      ← teacher waits, QR code shown
│   ├── play/                       ← teacher in-game controls
│   ├── end/                        ← final leaderboard
│   ├── export/                     ← download CSV results
│   └── repeat/                     ← clone session config
├── join/                           ← student enters code + nickname
├── play/<code>/                    ← student in-game view
│
├── quizzes/                        ← list teacher's quizzes
├── quizzes/create/                 ← create new quiz
├── quizzes/<id>/build/             ← interactive quiz builder
├── quizzes/<id>/delete/
├── quizzes/<id>/publish/
├── quizzes/<id>/launch/            ← launch quiz as live session
│
├── upload/                         ← question upload form
├── upload/results/                 ← upload result summary
├── upload/sample/<format>/         ← download sample template
│
└── api/
    ├── session/<code>/state/       ← versioned state poll (304 capable)
    ├── session/<code>/action/      ← teacher state machine (start/reveal/next/end)
    ├── join/                       ← student join (rate-limited 10/min/IP)
    ├── session/<code>/submit/      ← student answer submission
    ├── session/<code>/leaderboard/ ← public leaderboard
    ├── upload/                     ← JSON API file upload
    ├── questions/                  ← list visible questions (paginated)
    ├── quizzes/<id>/               ← quiz detail
    ├── quizzes/<id>/meta/          ← update quiz title/subject
    ├── quizzes/<id>/questions/     ← create question
    ├── quizzes/<id>/questions/<q>/ ← get/update/delete question
    └── quizzes/<id>/reorder/       ← reorder questions
```

---

## File Structure

```
brainbuzz/
├── models.py            BrainBuzzSession, SessionQuestion, Participant,
│                        Answer, Quiz, QuizQuestion, QuizOption
├── views.py             Teacher/student live-session views + JSON APIs
├── views_upload.py      Upload form, results, sample download, questions API
├── views_quiz.py        Quiz builder page views + JSON APIs
├── forms.py             QuestionUploadForm, QuestionSelectionForm
├── urls.py              All URL routing (see URL map above)
├── permissions.py       Role detection, scoping, visibility, decorators
├── managers.py          MathsQuestionsManager, CodingExercisesManager
│                        (with visible_to / by_topic / by_level / for_brainbuzz)
├── upload_service.py    QuestionUploadService (parse→scope→dedup→save)
├── upload_parsers.py    JSON / CSV / Excel parsers + validate_question
├── scoring.py           Kahoot-style points formula
├── ranking.py           Leaderboard ranking helpers
├── wizard.py            Session creation wizard helpers
├── admin.py             Django admin registrations
└── management/
    └── commands/
        ├── create_sample_templates.py   Generates JSON/CSV/Excel samples
        └── samples/
            ├── sample_maths_questions.json
            ├── sample_maths_questions.csv
            └── sample_maths_questions.xlsx
```
