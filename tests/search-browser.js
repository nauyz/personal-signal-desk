async page => {
  const report = [];
  const assert = (value, message) => { if (!value) throw new Error(message); };
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: 900});
    await page.goto('http://127.0.0.1:8876/');
    await page.locator('#search').waitFor();
    const input = page.locator('#search');
    const original = await input.elementHandle();
    await input.fill('OpenAI Artificial Intelligence');
    await page.waitForTimeout(500);
    for (let i = 0; i < 32; i++) {
      await page.keyboard.press('Backspace');
      await page.waitForTimeout(100);
      assert(await original.evaluate(el => el.isConnected && el === document.activeElement), 'Repeated backspace lost focus');
    }
    assert(await input.inputValue() === '', 'Repeated deletion did not clear input');
    for (const value of ['O', 'OpenAI', 'OpenA', '']) {
      await input.fill(value);
      await page.waitForTimeout(500);
      assert(await original.evaluate(el => el.isConnected && el === document.activeElement), 'Input replaced or blurred');
      const counts = await page.evaluate(async q => ({
        expected: (await window.cloudAPI('/api/content?q=' + encodeURIComponent(q))).page.total,
        actual: Number(document.querySelector('.results-head strong').textContent)
      }), value);
      assert(counts.expected === counts.actual, 'Wrong search results');
    }
    await input.fill('OpenAI');
    await input.evaluate(el => el.setSelectionRange(2, 2));
    await page.waitForTimeout(500);
    assert(await input.evaluate(el => el.selectionStart === 2 && el.selectionEnd === 2), 'Caret moved');
    await input.press('Backspace');
    await page.waitForTimeout(500);
    assert(await input.evaluate(el => el === document.activeElement && el.value === 'OenAI' && el.selectionStart === 1), 'Backspace lost caret');
    const priorURL = page.url();
    await input.dispatchEvent('compositionstart');
    await input.evaluate(el => { el.value = 'zhong'; el.dispatchEvent(new InputEvent('input', {bubbles:true,isComposing:true})); });
    await page.waitForTimeout(500);
    assert(page.url() === priorURL, 'Search fired during composition');
    await input.evaluate(el => { el.value = '中国'; el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'中国'})); });
    await page.waitForTimeout(500);
    assert(await original.evaluate(el => el.isConnected && el === document.activeElement && el.value === '中国'), 'Composition disrupted');
    report.push({width, typing:true, deletion:true, repeatedDeletion:true, clearing:true, caret:true, compositionEvents:true});
  }
  await page.evaluate(() => {
    window.originalCloudAPI = window.cloudAPI;
    window.cloudAPI = async path => {
      const q = new URL(path, location.origin).searchParams.get('q');
      if (q === 'failure') throw Error('test failure');
      const result = await window.originalCloudAPI(path);
      if (q === 'slow') { await new Promise(r => setTimeout(r, 900)); return {...result, page:{...result.page,total:999}}; }
      return result;
    };
  });
  await page.locator('#search').fill('slow');
  await page.waitForTimeout(450);
  await page.locator('#search').fill('OpenAI');
  await page.waitForTimeout(1100);
  assert(await page.locator('.results-head strong').innerText() !== '999', 'Stale response won');
  await page.locator('#search').fill('failure');
  await page.locator('[data-search-retry]').waitFor();
  assert(await page.locator('#search').evaluate(el => el === document.activeElement && el.value === 'failure'), 'Error lost input');
  await page.evaluate(() => { window.cloudAPI = window.originalCloudAPI; });
  await page.locator('[data-search-retry]').click();
  await page.locator('.results-head').waitFor();
  await page.locator('#search').fill('OpenAI');
  await page.locator('a[data-nav=facts]').click();
  await page.waitForTimeout(600);
  assert(await page.locator('h1').innerText() === '事实', 'Pending search overwrote navigation');
  await page.goto('http://127.0.0.1:8876/');
  await page.locator('#search').fill('OpenAI');
  await page.waitForTimeout(500);
  await page.screenshot({path:'search-fixed-mobile.png'});
  report.push({staleResponses:true,errorAndRetry:true,navigation:true});
  return report;
}
