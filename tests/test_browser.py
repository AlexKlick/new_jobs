"""
Playwright browser test for new_job_denjobs React app.
Run: python test_browser.py
Requires: pip install playwright && python -m playwright install chromium
"""
import asyncio
from playwright.async_api import async_playwright

BASE = 'http://localhost:5173'
PAGES = [
    {
        'path': '/',
        'name': 'JobTracker',
        'checks': ['Application Tracker', 'Total Jobs', 'Company', 'Role'],
    },
    {
        'path': '/job/1',
        'name': 'JobDetail',
        'checks': ['Back to Tracker', 'Company', 'Role', 'Apply Now'],
    },
    {
        'path': '/documents',
        'name': 'DocumentViewer',
        'checks': ['Select Job', 'Resume', 'Cover Letter'],
    },
    {
        'path': '/generation',
        'name': 'GenerationPage',
        'checks': ['Regenerate', 'Job', 'Generate'],
    },
    {
        'path': '/chat',
        'name': 'ChatInterface',
        'checks': ['Skill', 'TTS', 'input', 'message'],
    },
    {
        'path': '/skills',
        'name': 'SkillsPage',
        'checks': ['skill', 'Skill', 'Select'],
    },
]


async def test_pages():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        console_errors = []

        def on_console(msg):
            if msg.type == 'error':
                text = msg.text
                # Ignore non-critical
                if 'favicon' not in text and 'fonts.google' not in text:
                    console_errors.append(text)

        def on_page_error(err):
            console_errors.append(f'PAGE ERROR: {err}')

        page.on('console', on_console)
        page.on('pageerror', on_page_error)

        all_passed = True

        for page_info in PAGES:
            path = page_info['path']
            name = page_info['name']
            checks = page_info['checks']

            console_errors.clear()
            url = BASE + path
            print(f'\n=== Testing {name} ({url}) ===')

            try:
                response = await page.goto(url, wait_until='networkidle', timeout=20000)
                status = response.status if response else 0
                loaded = response is not None and 200 <= status < 400
                print(f'  Load: {"OK" if loaded else "FAIL"} (status {status})')
            except Exception as e:
                print(f'  Load: FAIL ({e})')
                all_passed = False
                continue

            if not loaded:
                all_passed = False
                continue

            # Wait a bit for React to hydrate
            await page.wait_for_timeout(1500)

            # Check body content
            body_text = (await page.text_content('body') or '').lower()
            body_html = (await page.content() or '').lower()

            content_found = 0
            for check in checks:
                if check.lower() in body_text or check.lower() in body_html:
                    content_found += 1
                else:
                    print(f'  Missing: "{check}"')

            print(f'  Content: {content_found}/{len(checks)} checks passed')

            # Console errors
            relevant = [e for e in console_errors
                        if 'React Router Future' not in e]
            if relevant:
                print(f'  Console errors ({len(relevant)}):')
                for e in relevant[:5]:
                    print(f'    - {e[:120]}')
                all_passed = False
            else:
                print('  Console errors: none')

            passed = content_found >= max(1, len(checks) // 2)
            print(f'  Result: {"PASS" if passed else "FAIL"}')
            if not passed:
                all_passed = False

        await browser.close()
        print(f'\n=== Overall: {"ALL PASSED" if all_passed else "SOME FAILURES"} ===')
        return all_passed


if __name__ == '__main__':
    result = asyncio.run(test_pages())
    exit(0 if result else 1)
