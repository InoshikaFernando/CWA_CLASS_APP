"""Generate small Teachworks-format .xls files for UI tests."""

from __future__ import annotations

import os
import time

import xlwt


def _unique_suffix() -> str:
    """Return a short unique suffix based on timestamp."""
    return str(int(time.time() * 1000))[-8:]


def create_student_xls(directory: str, suffix: str | None = None) -> tuple[str, list[dict]]:
    """Create a Teachworks Students .xls file with 2 test rows.

    Returns (file_path, list_of_student_dicts) where each dict has
    first_name, last_name, email keys for later verification.
    """
    suffix = suffix or _unique_suffix()
    filepath = os.path.join(directory, f"test_students_{suffix}.xls")

    headers = [
        "Type", "Student ID", "Customer ID", "First Name", "Last Name",
        "Family First", "Family Last", "Email", "Additional Email",
        "Mobile phone", "Home phone", "Family Email",
        "Family Additional Email", "Family phone", "Family Home Phone",
        "Family Work Phone", "Address", "Address Line 2", "City", "State",
        "Zip Code", "Country", "Time Zone", "Birth Date", "Start Date",
        "School", "Subjects", "Grade", "Additional Info", "Calendar Color",
        "Billing Method", "Student Cost", "Discount Rate", "Cost Premium",
        "Default Service", "Default Location", "Status", "Family Status",
        "Teachers", "Lesson Reminders", "Lesson Notes", "SMS Reminders",
        "User Account", "Confirmation Sent At", "Confirmed At",
        "Last Invoice Date", "Welcome Last Sent", "Created At", "Updated At",
        "Stripe ID", "Invoice Autopilots", "Student Groups", "Billing Groups",
    ]

    students = [
        {
            "first_name": f"TestStudent{suffix}A",
            "last_name": "Alpha",
            "email": f"student.a.{suffix}@test.local",
            "family_first": f"ParentA{suffix}",
            "family_last": "Alpha",
            "family_email": f"parent.a.{suffix}@test.local",
        },
        {
            "first_name": f"TestStudent{suffix}B",
            "last_name": "Beta",
            "email": f"student.b.{suffix}@test.local",
            "family_first": f"ParentB{suffix}",
            "family_last": "Beta",
            "family_email": f"parent.b.{suffix}@test.local",
        },
    ]

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Students")

    for col, header in enumerate(headers):
        ws.write(0, col, header)

    for row_idx, s in enumerate(students, start=1):
        ws.write(row_idx, 0, "Child")           # Type
        ws.write(row_idx, 1, row_idx)            # Student ID
        ws.write(row_idx, 2, row_idx)            # Customer ID
        ws.write(row_idx, 3, s["first_name"])    # First Name
        ws.write(row_idx, 4, s["last_name"])     # Last Name
        ws.write(row_idx, 5, s["family_first"])  # Family First
        ws.write(row_idx, 6, s["family_last"])   # Family Last
        ws.write(row_idx, 7, s["email"])         # Email
        ws.write(row_idx, 11, s["family_email"]) # Family Email
        ws.write(row_idx, 13, "0400000000")      # Family phone
        ws.write(row_idx, 26, "Year 7")          # Subjects (= Level in preset)
        ws.write(row_idx, 34, "Year 7 Monday")   # Default Service (= class_name)
        ws.write(row_idx, 36, "Active")          # Status
        ws.write(row_idx, 37, "Active")          # Family Status

    wb.save(filepath)
    return filepath, students


def create_teacher_xls(directory: str, suffix: str | None = None) -> tuple[str, list[dict]]:
    """Create a Teachworks Employees .xls file with 2 test rows.

    Returns (file_path, list_of_teacher_dicts) where each dict has
    first_name, last_name, email keys for later verification.
    """
    suffix = suffix or _unique_suffix()
    filepath = os.path.join(directory, f"test_teachers_{suffix}.xls")

    headers = [
        "Type", "Title", "First Name", "Last Name", "Email", "Mobile Phone",
        "Home Phone", "Address", "Address 2", "City", "State", "Zip",
        "Country", "Wage Type", "Employee Wage", "Wage Tier", "Birth Date",
        "Hire Date", "Position", "Subjects", "Calendar Color",
        "Additional Info", "Bio", "Status", "Lesson Reminders",
        "SMS Reminders", "Teachers Permission", "Staff Permission",
        "Students Permission", "Services Permission", "Lessons Permission",
        "Lesson Cost Permission", "Accounting Permission",
        "Reports Permission", "Settings Permission",
        "Student Contact Info Permission",
        "Events Duration Permission", "Others Lessons Permission",
        "Locations Permission", "Send Notes Permission", "User Account",
        "2FA", "Last Login", "Profile ID", "Welcome Last Sent",
        "Created at", "Updated at",
    ]

    teachers = [
        {
            "first_name": f"TestTeacher{suffix}A",
            "last_name": "Gamma",
            "email": f"teacher.a.{suffix}@test.local",
            "position": "Senior Teacher",
        },
        {
            "first_name": f"TestTeacher{suffix}B",
            "last_name": "Delta",
            "email": f"teacher.b.{suffix}@test.local",
            "position": "Junior Teacher",
        },
    ]

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Employees")

    for col, header in enumerate(headers):
        ws.write(0, col, header)

    for row_idx, t in enumerate(teachers, start=1):
        ws.write(row_idx, 0, "Teacher")          # Type
        ws.write(row_idx, 1, "Mr.")              # Title
        ws.write(row_idx, 2, t["first_name"])    # First Name
        ws.write(row_idx, 3, t["last_name"])     # Last Name
        ws.write(row_idx, 4, t["email"])         # Email
        ws.write(row_idx, 5, "0400000001")       # Mobile Phone
        ws.write(row_idx, 18, t["position"])     # Position
        ws.write(row_idx, 19, "Mathematics")     # Subjects
        ws.write(row_idx, 23, "Active")          # Status

    wb.save(filepath)
    return filepath, teachers


def create_parent_xls(
    directory: str,
    student_names: list[tuple[str, str]],
    suffix: str | None = None,
) -> tuple[str, list[dict]]:
    """Create a Teachworks Families .xls file with parent rows.

    ``student_names`` is a list of (first_name, last_name) tuples — one parent
    row is created per student, with the Children column set to
    "FirstName LastName" so the import can match.

    Returns (file_path, list_of_parent_dicts).
    """
    suffix = suffix or _unique_suffix()
    filepath = os.path.join(directory, f"test_parents_{suffix}.xls")

    headers = [
        "First Name", "Last Name", "Email", "Mobile Phone", "Children",
        "Status", "Address", "City", "Country",
    ]

    parents = []
    for idx, (s_first, s_last) in enumerate(student_names):
        parents.append({
            "first_name": f"Parent{suffix}{chr(65 + idx)}",
            "last_name": s_last,
            "email": f"parent.{chr(97 + idx)}.{suffix}@test.local",
            "children": f"{s_first} {s_last}",
        })

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Families")

    for col, header in enumerate(headers):
        ws.write(0, col, header)

    for row_idx, p in enumerate(parents, start=1):
        ws.write(row_idx, 0, p["first_name"])   # First Name
        ws.write(row_idx, 1, p["last_name"])     # Last Name
        ws.write(row_idx, 2, p["email"])         # Email
        ws.write(row_idx, 3, "0400000002")       # Mobile Phone
        ws.write(row_idx, 4, p["children"])      # Children
        ws.write(row_idx, 5, "Active")           # Status

    wb.save(filepath)
    return filepath, parents
