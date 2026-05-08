"""
Browser-based helpers for live environment testing.

These functions create test data through the actual UI forms — no Django ORM
needed. Used when running tests with --live-url against a deployed environment.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import Page


_RUN_ID = uuid.uuid4().hex[:6]
LIVE_PASSWORD = "TestPass123!"


def unique(name: str) -> str:
    return f"{name}_{_RUN_ID}"


def live_login(page: Page, base_url: str, username: str, password: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/accounts/login/")
    page.wait_for_load_state("networkidle")
    page.locator("#id_username").fill(username)
    page.locator("#id_password").fill(password)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=15_000)
    page.wait_for_load_state("domcontentloaded")
    # Handle complete-profile redirect if it appears
    if "/accounts/complete-profile/" in page.url:
        _complete_profile(page)


def _complete_profile(page: Page) -> None:
    """Fill and submit the complete-profile form if required."""
    first = page.locator("#id_first_name")
    if first.count() and not first.input_value():
        first.fill("Test")
    last = page.locator("#id_last_name")
    if last.count() and not last.input_value():
        last.fill("User")
    submit = page.locator("button[type='submit'], input[type='submit']").first
    if submit.count():
        submit.click()
        page.wait_for_load_state("domcontentloaded")


def live_logout(page: Page, base_url: str) -> None:
    page.evaluate(f"""() => {{
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '{base_url}/accounts/logout/';
        const csrf = document.createElement('input');
        csrf.type = 'hidden';
        csrf.name = 'csrfmiddlewaretoken';
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        csrf.value = match ? match[1] : '';
        form.appendChild(csrf);
        document.body.appendChild(form);
        form.submit();
    }}""")
    page.wait_for_load_state("domcontentloaded")


def register_hoi(page: Page, base_url: str) -> dict:
    """Register a Head of Institute via the public multi-step form.

    Returns dict with username, email, password, school_name.
    """
    school_name = f"Test School {_RUN_ID}"
    username = unique("hoi")
    email = f"{username}@test.local"

    page.goto(f"{base_url}/accounts/register/teacher-center/")
    page.wait_for_load_state("domcontentloaded")

    # Step 1: Account details
    page.locator("#id_center_name, [name='center_name']").fill(school_name)
    page.locator("#id_username, [name='username']").fill(username)
    page.locator("#id_email, [name='email']").fill(email)
    page.locator("#id_password1, [name='password1'], #id_password, [name='password']").first.fill(LIVE_PASSWORD)
    page.locator("#id_password2, [name='password2'], #id_confirm_password, [name='confirm_password']").first.fill(LIVE_PASSWORD)

    # Click next/submit for step 1
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")

    # Step 2: Company details (optional fields, just submit)
    submit = page.locator("button[type='submit'], input[type='submit']").first
    if submit.count():
        submit.click()
        page.wait_for_load_state("domcontentloaded")

    # Step 3: Plan selection — pick the first available plan
    plan_select = page.locator("#id_plan_id, [name='plan_id'], select").first
    if plan_select.count():
        options = plan_select.locator("option")
        for i in range(options.count()):
            val = options.nth(i).get_attribute("value")
            if val:
                plan_select.select_option(val)
                break
        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.click()
        page.wait_for_load_state("domcontentloaded")

    # Step 4: Terms acceptance
    terms = page.locator("#id_accept_terms, [name='accept_terms'], input[type='checkbox']").first
    if terms.count():
        terms.check()
        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.click()
        page.wait_for_load_state("domcontentloaded")

    return {
        "username": username,
        "email": email,
        "password": LIVE_PASSWORD,
        "school_name": school_name,
    }


def create_school(page: Page, base_url: str) -> dict:
    """Create a school via the admin dashboard. Must be logged in as admin.

    Returns dict with school_name and the school_id extracted from the redirect URL.
    """
    school_name = f"Test School {_RUN_ID}"

    page.goto(f"{base_url}/admin-dashboard/schools/create/")
    page.wait_for_load_state("domcontentloaded")

    page.locator("#id_name, [name='name']").first.fill(school_name)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")

    # Extract school ID from redirect URL
    import re
    match = re.search(r"/schools/(\d+)", page.url)
    school_id = int(match.group(1)) if match else None

    return {"school_name": school_name, "school_id": school_id}


def create_teacher(page: Page, base_url: str, school_id: int,
                   role: str = "teacher") -> dict:
    """Create a teacher via admin dashboard. Must be logged in as admin.

    Returns dict with username, email, password.
    """
    first_name = unique("Teacher")
    email = f"{unique('teacher')}@test.local"

    page.goto(f"{base_url}/admin-dashboard/schools/{school_id}/teachers/")
    page.wait_for_load_state("domcontentloaded")

    page.locator("#id_first_name, [name='first_name']").first.fill(first_name)
    page.locator("#id_last_name, [name='last_name']").first.fill("Test")
    page.locator("#id_email, [name='email']").first.fill(email)
    page.locator("#id_password, [name='password']").first.fill(LIVE_PASSWORD)

    role_select = page.locator("#id_role, [name='role']").first
    if role_select.count():
        role_select.select_option(role)

    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")

    # Username is auto-generated from email
    username = email.split("@")[0]
    return {
        "username": username,
        "email": email,
        "password": LIVE_PASSWORD,
        "first_name": first_name,
    }


def create_student(page: Page, base_url: str, school_id: int) -> dict:
    """Create a student via admin dashboard. Must be logged in as admin.

    Returns dict with username, email, password.
    """
    first_name = unique("Student")
    email = f"{unique('student')}@test.local"

    page.goto(f"{base_url}/admin-dashboard/schools/{school_id}/students/")
    page.wait_for_load_state("domcontentloaded")

    page.locator("#id_first_name, [name='first_name']").first.fill(first_name)
    page.locator("#id_last_name, [name='last_name']").first.fill("Test")
    page.locator("#id_email, [name='email']").first.fill(email)
    page.locator("#id_password, [name='password']").first.fill(LIVE_PASSWORD)

    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")

    username = email.split("@")[0]
    return {
        "username": username,
        "email": email,
        "password": LIVE_PASSWORD,
        "first_name": first_name,
    }


def create_department(page: Page, base_url: str, school_id: int) -> dict:
    """Create a department via admin dashboard. Must be logged in as admin.

    Returns dict with dept_name.
    """
    dept_name = f"Maths {_RUN_ID}"

    page.goto(f"{base_url}/admin-dashboard/schools/{school_id}/departments/create/")
    page.wait_for_load_state("domcontentloaded")

    page.locator("#id_name, [name='name']").first.fill(dept_name)

    # Select first available subject if any
    subject_cb = page.locator("input[name='subjects']").first
    if subject_cb.count():
        subject_cb.check()

    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")

    return {"dept_name": dept_name}
