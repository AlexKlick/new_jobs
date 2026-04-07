/**
 * E2E Playwright tests for core application flows (E2E-01).
 *
 * Tests verify all major flows work end-to-end with health check gate
 * and 5000ms soft assertions per acceptance criteria.
 */

const { chromium } = require('@playwright/test');

const BASE = 'http://localhost:8080';
const UI_BASE = 'http://localhost:5173';

// Health check gate - verify backend is reachable before running tests
async function healthCheck() {
  try {
    const response = await fetch(`${BASE}/health`, { timeout: 5000 });
    if (!response.ok) {
      throw new Error(`Health check failed: ${response.status}`);
    }
    const data = await response.json();
    console.log(`Health check passed: ${data.status}`);
    return true;
  } catch (e) {
    console.error(`Health check failed: ${e.message}`);
    return false;
  }
}

async function waitForWithTimeout(page, selector, timeout = 5000) {
  // Soft assertion with 5000ms timeout per E2E-01 acceptance criteria
  try {
    await page.waitForSelector(selector, { timeout });
    return true;
  } catch {
    return false;
  }
}

async function runE2ETests() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  let passed = 0;
  let failed = 0;

  // Health check gate - fail fast if backend not available
  console.log('\n=== Health Check Gate ===');
  const healthy = await healthCheck();
  if (!healthy) {
    console.error('FATAL: Backend health check failed. Aborting E2E tests.');
    await browser.close();
    process.exit(1);
  }

  // Test 1: Text chat flow
  console.log('\n=== Test 1: Text Chat Flow ===');
  try {
    await page.goto(`${UI_BASE}/chat`, { waitUntil: 'networkidle', timeout: 15000 });

    // Check chat interface elements exist
    const inputExists = await waitForWithTimeout(page, '.chat-text-input', 5000);
    const sendBtnExists = await waitForWithTimeout(page, '.chat-send-btn', 5000);

    if (inputExists && sendBtnExists) {
      // Type a test message
      await page.fill('.chat-text-input', 'Hello, this is a test message');
      await page.click('.chat-send-btn');

      // Wait for response (soft assertion with 5000ms)
      const responseReceived = await waitForWithTimeout(page, '.chat-message.assistant', 5000);
      if (responseReceived) {
        console.log('  PASS: Text chat flow works');
        passed++;
      } else {
        console.log('  FAIL: No assistant response received');
        failed++;
      }
    } else {
      console.log('  FAIL: Chat input elements not found');
      failed++;
    }
  } catch (e) {
    console.log(`  FAIL: ${e.message}`);
    failed++;
  }

  // Test 2: Skill selection flow
  console.log('\n=== Test 2: Skill Selection Flow ===');
  try {
    const skillSelectExists = await waitForWithTimeout(page, '#skill-select', 5000);
    const skillFilterExists = await waitForWithTimeout(page, '.chat-skill-filter select', 5000);

    if (skillSelectExists && skillFilterExists) {
      // Test skill filter dropdown
      await page.selectOption('.chat-skill-filter select', 'swe');
      const sweSelected = await page.$eval('.chat-skill-filter select', el => el.value);

      if (sweSelected === 'swe') {
        console.log('  PASS: Skill filter works');
        passed++;
      } else {
        console.log('  FAIL: Skill filter did not select SWE');
        failed++;
      }
    } else {
      console.log('  FAIL: Skill selector elements not found');
      failed++;
    }
  } catch (e) {
    console.log(`  FAIL: ${e.message}`);
    failed++;
  }

  // Test 3: Session selector flow
  console.log('\n=== Test 3: Session Selector Flow ===');
  try {
    const sessionSelectExists = await waitForWithTimeout(page, '.session-selector select', 5000);

    if (sessionSelectExists) {
      // Check that "New Session" option exists
      const newSessionOption = await page.$('.session-selector select option[value=""]');
      if (newSessionOption) {
        console.log('  PASS: Session selector has New Session option');
        passed++;
      } else {
        console.log('  FAIL: New Session option not found');
        failed++;
      }
    } else {
      console.log('  FAIL: Session selector not found');
      failed++;
    }
  } catch (e) {
    console.log(`  FAIL: ${e.message}`);
    failed++;
  }

  // Test 4: TTS toggle exists
  console.log('\n=== Test 4: TTS Toggle Flow ===');
  try {
    const ttsToggleExists = await waitForWithTimeout(page, '.tts-toggle', 5000);

    if (ttsToggleExists) {
      // Click TTS toggle to test interaction
      await page.click('.tts-toggle');
      console.log('  PASS: TTS toggle is clickable');
      passed++;
    } else {
      console.log('  FAIL: TTS toggle not found');
      failed++;
    }
  } catch (e) {
    console.log(`  FAIL: ${e.message}`);
    failed++;
  }

  // Test 5: Job context panel flow
  console.log('\n=== Test 5: Job Context Panel Flow ===');
  try {
    // JobContextPanel only shows when jobIndex is not null
    // Check that the toggle button exists when navigating with a job
    await page.goto(`${UI_BASE}/chat`, { waitUntil: 'networkidle', timeout: 15000 });

    // First select a job via URL or ensure we have jobs
    const jobSwitcherExists = await waitForWithTimeout(page, '.job-switcher', 5000);

    if (jobSwitcherExists) {
      console.log('  PASS: Job switcher exists');
      passed++;
    } else {
      console.log('  FAIL: Job switcher not found');
      failed++;
    }
  } catch (e) {
    console.log(`  FAIL: ${e.message}`);
    failed++;
  }

  await browser.close();

  console.log(`\n=== E2E Test Results: ${passed} passed, ${failed} failed ===`);
  process.exit(failed > 0 ? 1 : 0);
}

// Run tests
runE2ETests().catch(e => {
  console.error('E2E test runner failed:', e);
  process.exit(1);
});
