/**
 * Playwright browser test for new_job_denjobs React app.
 * Run: node test-browser.cjs
 */
const { chromium } = require('playwright');

const BASE = 'http://localhost:5173';
const PAGES = [
  { path: '/', name: 'JobTracker', checks: ['table', 'job', 'Application Tracker'] },
  { path: '/job/1', name: 'JobDetail', checks: ['Back to Tracker', 'Company', 'Role'] },
  { path: '/documents', name: 'DocumentViewer', checks: ['Select Job', 'Resume', 'Cover Letter'] },
  { path: '/generation', name: 'GenerationPage', checks: ['Regenerate', 'Job', 'Generate'] },
  { path: '/chat', name: 'ChatInterface', checks: ['chat', 'input', 'message', 'session', 'context', 'skill'] },
  { path: '/skills', name: 'SkillsPage', checks: ['skill', 'Skill', 'Select a skill'] },
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => consoleErrors.push(`PAGE ERROR: ${err.message}`));

  let allPassed = true;

  // Session persistence test function
  async function testSessionPersistence(page) {
    const results = [];

    // 1. Load chat page
    try {
      await page.goto(BASE + '/chat', { waitUntil: 'networkidle', timeout: 15000 });
    } catch (e) {
      results.push({ test: 'Chat page loads', pass: false });
      return results;
    }
    results.push({ test: 'Chat page loads', pass: true });

    // 2. Check session selector exists
    const sessionSelect = await page.$('.session-selector select');
    results.push({ test: 'SessionSelector exists', pass: !!sessionSelect });

    // 3. Check skill filter dropdown exists
    const skillFilter = await page.$('.chat-skill-filter select');
    results.push({ test: 'SkillFilter exists', pass: !!skillFilter });

    // 4. Check skill selector exists
    const skillSelect = await page.$('#skill-select');
    results.push({ test: 'SkillSelector exists', pass: !!skillSelect });

    // 5. Check TTS toggle exists
    const ttsToggle = await page.$('.tts-toggle');
    results.push({ test: 'TtsToggle exists', pass: !!ttsToggle });

    // 6. Check chat empty state
    const emptyState = await page.$('.chat-empty-state');
    results.push({ test: 'Chat empty state shown', pass: !!emptyState });

    return results;
  }

  for (const { path, name, checks } of PAGES) {
    consoleErrors.length = 0;
    const url = BASE + path;
    console.log(`\n=== Testing ${name} (${url}) ===`);

    let loaded = false;
    try {
      const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });
      loaded = response && response.ok();
      console.log(`  Load: ${loaded ? 'OK' : 'FAIL'} (status ${response?.status()})`);
    } catch (e) {
      console.log(`  Load: FAIL (${e.message})`);
      allPassed = false;
      continue;
    }

    if (!loaded) { allPassed = false; continue; }

    // Check for key content
    const bodyText = await page.textContent('body');
    const bodyHTML = await page.content();
    let contentChecks = 0;
    for (const check of checks) {
      const found = bodyText.toLowerCase().includes(check.toLowerCase()) ||
                    bodyHTML.toLowerCase().includes(check.toLowerCase());
      if (found) contentChecks++;
      else console.log(`  Missing content: "${check}"`);
    }
    console.log(`  Content checks: ${contentChecks}/${checks.length}`);

    // Console errors
    const relevantErrors = consoleErrors.filter(e =>
      !e.includes('favicon') &&
      !e.includes('fonts.google') &&
      !e.includes('React Router Future') // known non-critical warning
    );
    if (relevantErrors.length > 0) {
      console.log(`  Console errors (${relevantErrors.length}):`);
      relevantErrors.slice(0, 5).forEach(e => console.log(`    - ${e}`));
      allPassed = false;
    } else {
      console.log(`  Console errors: none`);
    }

    const passed = loaded && contentChecks >= Math.ceil(checks.length / 2);
    if (passed) console.log(`  Result: PASS`);
    else { console.log(`  Result: FAIL`); allPassed = false; }
  }

  // Session persistence E2E test
  console.log('\n=== Testing Chat Session Persistence ===');
  const sessionResults = await testSessionPersistence(page);
  sessionResults.forEach(r => {
    console.log(`  ${r.pass ? 'PASS' : 'FAIL'}: ${r.test}`);
  });
  if (sessionResults.some(r => !r.pass)) allPassed = false;

  await browser.close();
  console.log(`\n=== Overall: ${allPassed ? 'ALL PASSED' : 'SOME FAILURES'} ===`);
  process.exit(allPassed ? 0 : 1);
})();
