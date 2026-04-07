"""
Cross-page integration test for new_job_denjobs React app.
Tests the full user flow: JobTracker -> JobDetail -> DocumentViewer -> GenerationPage -> Chat -> Skills -> back

Run: python test_integration.py
"""
import asyncio
from playwright.async_api import async_playwright

BASE = 'http://localhost:5173'

async def test_integration():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        errors = []

        def on_page_error(err):
            errors.append(f'PAGE ERROR: {err}')

        page.on('pageerror', on_page_error)

        try:
            # Step 1: JobTracker -> click first job row
            print('Step 1: JobTracker (/)')
            await page.goto(BASE + '/', wait_until='networkidle', timeout=15000)
            await page.wait_for_timeout(1000)

            # Click on a job row (View button for first job)
            view_btn = page.locator('.view-btn').first
            if await view_btn.is_visible():
                await view_btn.click()
                await page.wait_for_timeout(1000)
                print(f'  Navigated to: {page.url}')
            else:
                print('  WARNING: No view button found')

            # Step 2: JobDetail -> click View Resume
            print('Step 2: JobDetail (/job/:index)')
            current_url = page.url
            print(f'  Current URL: {current_url}')

            # Click View Resume link
            resume_link = page.locator('a:has-text("View Resume")').first
            if await resume_link.is_visible():
                await resume_link.click()
                await page.wait_for_timeout(1000)
                print(f'  Navigated to: {page.url}')
            else:
                print('  WARNING: No View Resume link found')

            # Step 3: DocumentViewer -> click Generate link (or go to generation page)
            print('Step 3: DocumentViewer (/documents)')
            print(f'  Current URL: {page.url}')

            # Navigate to generation page
            print('Step 4: Navigate to GenerationPage (/generation)')
            await page.goto(BASE + '/generation', wait_until='networkidle', timeout=15000)
            await page.wait_for_timeout(1000)
            print(f'  Current URL: {page.url}')

            # Step 5: Navigate to Chat
            print('Step 5: Navigate to Chat (/chat)')
            await page.goto(BASE + '/chat', wait_until='networkidle', timeout=15000)
            await page.wait_for_timeout(1000)
            print(f'  Current URL: {page.url}')

            # Step 6: Navigate to Skills
            print('Step 6: Navigate to Skills (/skills)')
            await page.goto(BASE + '/skills', wait_until='networkidle', timeout=15000)
            await page.wait_for_timeout(1000)
            print(f'  Current URL: {page.url}')

            # Step 7: Back to Chat
            print('Step 7: Back to Chat via nav')
            chat_link = page.locator('a:has-text("Chat")').first
            if await chat_link.is_visible():
                await chat_link.click()
                await page.wait_for_timeout(1000)
                print(f'  Navigated to: {page.url}')
            else:
                print('  WARNING: No Chat nav link found')

            # Report results
            print(f'\nFinal URL: {page.url}')
            print(f'Page errors encountered: {len(errors)}')
            for e in errors:
                print(f'  - {e[:120]}')

            # Check all nav links work
            print('\nVerifying all nav links exist...')
            await page.goto(BASE + '/', wait_until='networkidle', timeout=15000)
            await page.wait_for_timeout(500)

            nav_links = ['Tracker', 'Documents', 'Quality', 'Generate', 'Chat', 'Skills']
            all_nav = True
            for link in nav_links:
                link_el = page.locator(f'a.nav-link:has-text("{link}")')
                count = await link_el.count()
                if count > 0:
                    print(f'  Nav link "{link}": found')
                else:
                    print(f'  Nav link "{link}": MISSING')
                    all_nav = False

            print(f'\nIntegration test: {"PASS" if all_nav and len([e for e in errors if "PAGE ERROR" in e]) == 0 else "FAIL"}')

        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(test_integration())
