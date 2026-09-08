async (page) => {
  const expected = {
    facts: '关注发生了什么：',
    content: '关注具体发布了什么：',
  };
  for (const [device, width, height] of [['desktop', 1440, 960], ['mobile', 390, 844]]) {
    await page.setViewportSize({width, height});
    for (const route of ['content', 'facts']) {
      await page.goto(`http://127.0.0.1:8876/#/${route}`);
      await page.locator('.page-heading p').filter({hasText: expected[route]}).waitFor();
      const label = await page.locator(`.sidebar nav > a[data-nav="${route}"] small`).textContent();
      if (label !== `AI Hot ${route === 'facts' ? '事实' : '内容'}`) throw Error('Incorrect navigation label');
      const copyFits = await page.locator('.page-heading').evaluate(el => {
        const rect = el.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= innerWidth && el.scrollWidth <= el.clientWidth;
      });
      if (!copyFits) throw Error('Page description overflows');
      await page.screenshot({path: `information-${route}-${device}.png`});
    }
  }
  return {navigationLabels: 'passed', descriptions: 'passed', viewports: [1440, 390]};
}
