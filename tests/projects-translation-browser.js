async (page) => {
  await page.goto('http://127.0.0.1:8876/');
  await page.locator('#search:not(:disabled)').waitFor();
  await page.evaluate(() => {
    const original = window.cloudAPI;
    window.cloudAPI = async path => path === '/api/projects' ? {
      snapshot: {fetched_at:'2026-09-12T00:00:00Z'},
      items: [
        {rank:1,full_name:'new-owner/new-project',description:'A browser tool',description_zh:'浏览器工具 <script>不是代码</script>',repo_url:'https://github.com/new-owner/new-project'},
        {rank:2,full_name:'test/chinese',description:'中文项目',description_zh:'中文项目',repo_url:'https://github.com/test/chinese'},
        {rank:3,full_name:'test/pending',description:'Pending translation',description_zh:'',repo_url:'https://github.com/test/pending'}
      ]
    } : original(path);
  });
  await page.locator('[data-nav="projects"]').click();
  await page.locator('.project-card').first().waitFor();
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:900});
    if (await page.locator('.project-description-zh').count() !== 1) throw Error('Missing translation or duplicate Chinese');
    if (!(await page.locator('.project-description-zh').innerText()).includes('<script>')) throw Error('Translation escaping failed');
    if (await page.locator('.project-description script').count()) throw Error('Unsafe translation HTML');
    if (!(await page.locator('.project-card').nth(2).innerText()).includes('Pending translation')) throw Error('Failure hid original');
    await page.screenshot({path:'projects-translation-'+width+'.png'});
  }
  return {newProjects:true, bilingual:true, escaping:true, chineseDedup:true, missingTranslation:true,viewports:[1440,390]};
}
