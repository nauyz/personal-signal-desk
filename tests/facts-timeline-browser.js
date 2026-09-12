async (page) => {
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  // Isolated layout fixtures, never written to the source database or published data.
  const items = [
    {title:'开源工具新增本地检索支持', latest_at:'2026-09-07T15:30:00Z', rank:1, status:'settled'},
    {title:'模型团队公布新一轮评测结果', latest_at:'2026-09-08T03:30:00Z', rank:3, status:'active'},
    {title:'开发者发布多语言文档与使用教程', latest_at:'2026-09-07T17:00:00Z', rank:2},
    {title:'尚未提供信号时间的事件', latest_at:'invalid', rank:4},
  ].map(item => ({...item, source_count:3, signal_count:12, representative_source:'示例信源',
    digest:'事件综述保留在正文阅读区，不再放入独立卡片。相关报道、讨论与不同来源可以沿时间线连续阅读，完整文字不会被截断。',
    story_url:'https://example.com/story', original_url:'https://example.com/source'}));
  for (const [device,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
    await page.setViewportSize({width,height});
    await page.goto('http://127.0.0.1:8876/');
    await page.locator('#search:not(:disabled)').waitFor();
    await page.evaluate(items => {
      const original = window.cloudAPI;
      window.cloudAPI = path => path === '/api/facts?view=events' ? Promise.resolve({items}) : original(path);
    },items);
    await page.locator('nav a[data-nav=facts]').first().click();
    await page.locator('.facts-timeline').waitFor();
    const titles = await page.locator('.fact-card h3').allTextContents();
    assert(JSON.stringify(titles) === JSON.stringify([items[1],items[2],items[0],items[3]].map(x=>x.title)), 'Chronological order');
    assert(await page.locator('.timeline-group').count() === 3, 'Shanghai date grouping');
    assert(await page.locator('.timeline-entry time').first().textContent() === '11:30', 'Shanghai clock');
    assert(await page.locator('.timeline-entry time:not([datetime])').count() === 1, 'Unknown time fallback');
    assert(await page.locator('.fact-card .card-links a').count() === 8, 'Source links preserved');
    assert(await page.locator('.fact-card').first().evaluate(el => {
      const style = getComputedStyle(el);
      return style.borderLeftWidth === '0px' && style.borderRadius === '0px' && style.backgroundColor === 'rgba(0, 0, 0, 0)';
    }), 'Unboxed timeline rows');
    assert(await page.locator('.facts-timeline').evaluate(el => el.scrollWidth <= el.clientWidth), 'Timeline overflow');
    await page.screenshot({path:`facts-timeline-${device}.png`});
    await page.evaluate(async () => {
      const original = window.cloudAPI;
      window.cloudAPI = path => path === '/api/facts?view=events' ? Promise.resolve({items:[]}) : original(path);
      await renderFacts();
    });
    assert(await page.locator('.facts-empty').evaluate(el => getComputedStyle(el).borderTopWidth === '0px'), 'Unboxed empty state');
    await page.screenshot({path:`facts-timeline-empty-${device}.png`});
  }
  return {order:true, dateGroups:true, unknownTime:true, links:true, unboxed:true, viewports:[1440,390]};
}
