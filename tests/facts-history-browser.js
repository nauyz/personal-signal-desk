async (page) => {
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const fixedNow = Date.parse('2026-09-13T12:00:00Z');
  await page.addInitScript(now => { Date.now = () => now; }, fixedNow);
  const today = new Date(fixedNow+8*3600000).toISOString().slice(0,10);
  const ago = days => new Date(fixedNow+8*3600000-days*86400000).toISOString().slice(0,10);
  const item = (id,day,title) => ({aihot_story_id:id,archive_date:day,observed_at:day+'T08:00:00.000000Z',latest_at:day+'T08:00:00Z',title,rank:1,source_count:3,signal_count:10,representative_source:'测试信源',digest:'测试专用综述，验证时间筛选与历史版本。',story_url:'https://example.com/story',original_url:'https://example.com/source',recovered:true});
  const records = [item('one',today,'最新版本'),item('two',ago(20),'二十天前的事件'),{...item('three',ago(50),'五十天前的事件'),archive_date:today},
    {...item('edge',today,'七天边界'),latest_at:new Date(fixedNow-7*86400000).toISOString()},
    {...item('outside',today,'超过七天一毫秒'),latest_at:new Date(fixedNow-7*86400000-1).toISOString()},
    {...item('future',today,'未来事件'),latest_at:new Date(fixedNow+1).toISOString()},
    {...item('unknown',today,'时间未知'),latest_at:null}];
  // Isolated test data exercises the actual static adapter, never the real database.
  await page.route('**/data/facts-*.json', route => route.fulfill({json:{items:records,count:records.length,dates:[today,ago(20),ago(40),ago(50)]}}));
  for (const [device,width,height] of [['desktop',1440,1000],['comment',479,731],['mobile',390,844]]) {
    await page.setViewportSize({width,height});
    await page.goto('http://127.0.0.1:8876/#/facts?view=history');
    await page.locator('[data-facts-range="all"][aria-pressed="true"]').waitFor();
    assert(await page.locator('.fact-card').count() === 7, 'All events default, including unknown time');
    assert(await page.locator('#facts-date, [data-facts-view]').count() === 0, 'No dropdown or latest/history tabs');
    await page.locator('[data-facts-range="48h"]').click();
    await page.locator('[data-facts-range="48h"][aria-pressed="true"]').waitFor();
    assert(await page.locator('.fact-card').count() === 1, '48 hours excludes future and unknown time');
    await page.locator('[data-facts-range="all"]').click();
    await page.locator('[data-facts-range="all"][aria-pressed="true"]').waitFor();
    await page.screenshot({path:'facts-history-all-'+device+'.png',fullPage:true});
    await page.locator('[data-facts-range="7d"]').click();
    await page.locator('[data-facts-range="7d"][aria-pressed="true"]').waitFor();
    assert(await page.locator('.fact-card').count() === 2, 'Rolling seven days includes exact boundary but not one ms earlier');
    await page.locator('[data-facts-range="30d"]').click();
    await page.locator('[data-facts-range="30d"][aria-pressed="true"]').waitFor();
    assert(await page.locator('.fact-card').count() === 4, 'Thirty days uses event time, not archive date');
    await page.locator('[data-facts-range="custom"]').click();
    await page.getByLabel('开始日期',{exact:true}).fill(ago(20));
    await page.getByLabel('结束日期',{exact:true}).fill(ago(20));
    await page.getByRole('button',{name:'应用筛选'}).click();
    await page.getByText('二十天前的事件',{exact:true}).waitFor();
    assert(await page.locator('.fact-card').count() === 1, 'Custom range uses event date');
    await page.reload();
    await page.getByText('二十天前的事件',{exact:true}).waitFor();
    assert(await page.locator('.fact-card a').count() === 2, 'Source links');
    assert(await page.locator('body').evaluate(el=>el.scrollWidth<=innerWidth), 'No overflow');
    await page.screenshot({path:'facts-history-custom-'+device+'.png',fullPage:true});
    await page.getByLabel('开始日期',{exact:true}).fill(today);
    await page.getByRole('button',{name:'应用筛选'}).click();
    await page.getByText('开始日期不能晚于结束日期',{exact:true}).waitFor();
    await page.locator('[data-facts-range="all"]').click();
    await page.locator('[data-facts-range="all"][aria-pressed="true"]').waitFor();
    await page.goBack();
    await page.getByText('二十天前的事件',{exact:true}).waitFor();
    await page.goto('http://127.0.0.1:8876/#/facts?view=history&date=2020-01-01');
    await page.getByRole('heading',{name:'这个时间范围没有已收录的事件'}).waitFor();
    await page.screenshot({path:'facts-history-empty-'+device+'.png',fullPage:true});
  }
  const freshness = await page.evaluate(() => {
    const make = (status, hours) => factsFreshness({sync:[{resource:'hot-topics',last_status:status,last_synced_at:new Date(Date.now()-hours*3600000).toISOString()}]});
    return {ok:make('ok',0), unchanged:make('not-modified',0), old:make('ok',4), failed:make('error',0), missing:factsFreshness({})};
  });
  assert(!freshness.ok.stale && freshness.ok.html.includes('数据最后采集'), 'Fresh successful collection');
  assert(!freshness.unchanged.stale && freshness.unchanged.html.includes('无变化'), '304 is a check, not new data');
  assert(freshness.old.stale && freshness.failed.stale && freshness.missing.stale, 'Old, failed, unknown sources warn');
  assert(freshness.failed.html.includes('最近采集失败') && !freshness.failed.html.includes('数据最后采集'), 'Failure must not claim refreshed data');
  return {all:true,ranges:true,dedup:true,custom:true,validation:true,refresh:true,back:true,legacyURL:true,freshness:true,viewports:[1440,479,390]};
}
