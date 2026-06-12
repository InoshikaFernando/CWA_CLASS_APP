"""
smoke_test.py — Browser smoke test against a deployed environment.

Validates that the app, database, and migrations are working by logging
in with sanitized test credentials and checking key pages load.

Usage:
    python smoke_test.py https://dev.wizardslearninghub.co.nz
    python smoke_test.py https://dev.wizardslearninghub.co.nz --headed
    python smoke_test.py https://dev.wizardslearninghub.co.nz --headed --slow 500

    # Liveness-only (no login) — safe to run against PRODUCTION, which has
    # no sanitised test users:
    python smoke_test.py https://wizardslearninghub.co.nz --public-only
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright, expect


# Override for sanitised non-prod environments via SMOKE_PASSWORD.
PASSWORD = os.environ.get("SMOKE_PASSWORD", "Password1!")


def login(page, base_url, email):
    page.goto(f"{base_url}/accounts/login/")
    page.wait_for_load_state("domcontentloaded")
    page.locator("#id_username").fill(email)
    page.locator("#id_password").fill(PASSWORD)
    page.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=15_000)
    page.wait_for_load_state("domcontentloaded")


def check_page(page, base_url, path, expect_text=None, expect_status=True):
    """Navigate and verify the page loads without a server error."""
    url = f"{base_url}{path}"
    resp = page.goto(url)
    page.wait_for_load_state("domcontentloaded")

    status = resp.status if resp else 0
    ok = 200 <= status < 400

    if expect_text:
        try:
            page.locator(f"text={expect_text}").first.wait_for(timeout=5_000)
        except Exception:
            ok = False

    label = "PASS" if ok else "FAIL"
    print(f"  [{label}] {path} (HTTP {status})")
    return ok


def run_smoke(base_url, headed=False, slow_mo=0, public_only=False):
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, slow_mo=slow_mo)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # ----------------------------------------------------------
        # 0. Deep health check — DB, migrations, cache (no auth needed)
        # ----------------------------------------------------------
        print("\n=== Deep health (/api/health/?deep=1) ===")
        resp = page.goto(f"{base_url}/api/health/?deep=1")
        health_ok = bool(resp and resp.status == 200)
        try:
            body = resp.json() if resp else {}
            print(f"  [{'PASS' if health_ok else 'FAIL'}] status={body.get('status')} "
                  f"version={body.get('version')} checks={body.get('checks')}")
        except Exception:
            print(f"  [{'PASS' if health_ok else 'FAIL'}] HTTP {resp.status if resp else 0}")
        results.append(health_ok)

        # ----------------------------------------------------------
        # 1. Login page loads
        # ----------------------------------------------------------
        print("\n=== Login page ===")
        results.append(check_page(page, base_url, "/accounts/login/", "Sign In"))

        # ----------------------------------------------------------
        # 2. Login with a known sanitized user (user1@test.local)
        #    Skipped in --public-only mode (e.g. against production, which
        #    has no sanitised test users).
        # ----------------------------------------------------------
        if public_only:
            print("\n=== Login === (skipped: --public-only)")
        else:
            print("\n=== Login as user1@test.local ===")
            try:
                login(page, base_url, "user1@test.local")
                current = page.url
                logged_in = "/accounts/login" not in current
                print(f"  [{'PASS' if logged_in else 'FAIL'}] Login redirect → {current}")
                results.append(logged_in)
            except Exception as e:
                print(f"  [FAIL] Login failed: {e}")
                results.append(False)

        # ----------------------------------------------------------
        # 3. Public home loads
        # ----------------------------------------------------------
        print("\n=== Home page ===")
        results.append(check_page(page, base_url, "/"))

        # ----------------------------------------------------------
        # 4. Static files serving
        # ----------------------------------------------------------
        print("\n=== Static files ===")
        resp = page.goto(f"{base_url}/static/css/output.css")
        static_ok = resp and resp.status == 200
        print(f"  [{'PASS' if static_ok else 'FAIL'}] /static/css/output.css (HTTP {resp.status if resp else 0})")
        results.append(static_ok)

        # ----------------------------------------------------------
        # 5. Admin site loads (if user is staff)
        # ----------------------------------------------------------
        print("\n=== Admin site ===")
        results.append(check_page(page, base_url, "/admin/", "Django administration"))

        # ----------------------------------------------------------
        # 6. API / key pages
        # ----------------------------------------------------------
        print("\n=== Key pages ===")
        pages_to_check = [
            ("/accounts/login/", "Sign In"),
            ("/maths/", None),
            ("/coding/", None),
        ]
        for path, text in pages_to_check:
            results.append(check_page(page, base_url, path, text))

        # ----------------------------------------------------------
        # Summary
        # ----------------------------------------------------------
        browser.close()

    passed = sum(results)
    total = len(results)
    failed = total - passed

    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 40}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smoke test a deployed CWA environment")
    parser.add_argument("url", help="Base URL (e.g. https://dev.wizardslearninghub.co.nz)")
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    parser.add_argument("--slow", type=int, default=0, help="Slow down actions by N ms")
    parser.add_argument("--public-only", action="store_true",
                        help="Skip the authenticated login step — liveness only "
                             "(safe against production, which has no sanitised users)")
    args = parser.parse_args()

    sys.exit(run_smoke(args.url.rstrip("/"), headed=args.headed, slow_mo=args.slow,
                       public_only=args.public_only))
