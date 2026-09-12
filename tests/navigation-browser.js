async page => {
  const assert = (value, message) => { if (!value) throw Error(message); };
  await page.setViewportSize({width:1440,height:900});
  const results = [];
  for (const nav of ['facts','projects','launches','xrank','hn']) {
    for (const fail of [false,true]) {
      await page.goto('http://127.0.0.1:8876/');
      await page.waitForFunction(()=>!document.querySelector('#search').disabled);
      await page.evaluate(({nav,fail}) => {
        const original = window.cloudAPI;
        window.cloudAPI = async path => {
          if (!path.startsWith('/api/'+nav)) return original(path);
          const data = await original(path);
          await new Promise(r=>setTimeout(r,700));
          if (fail) throw Error('delayed source failure');
          return data;
        };
      },{nav,fail});
      await page.locator('nav a[data-nav='+nav+']').first().click();
      await page.locator('nav a[data-nav=content]').first().click();
      await page.locator('#search:not(:disabled)').waitFor();
      await page.locator('#search').focus();
      await page.waitForTimeout(1000);
      assert(await page.locator('h1').innerText() === '内容', nav+' overwrote content');
      assert(await page.locator('#search').evaluate(el=>el===document.activeElement), nav+' stole focus');
      results.push({nav,fail,passed:true});
    }
  }
  await page.goto('http://127.0.0.1:8876/');
  await page.waitForFunction(()=>!document.querySelector('#search').disabled);
  await page.evaluate(()=>{
    const original=window.cloudAPI; let calls=0;
    window.cloudAPI=async path=>{
      if(path!=='/api/facts?view=events') return original(path);
      if(++calls===1) {
        await new Promise(r=>setTimeout(r,700));
        return {items:[{title:'STALE RESPONSE',rank:1}]};
      }
      return {items:[]};
    };
  });
  await page.locator('nav a[data-nav=facts]').first().click();
  await page.locator('nav a[data-nav=content]').first().click();
  await page.locator('nav a[data-nav=facts]').first().click();
  await page.waitForTimeout(1000);
  assert(await page.locator('h1').innerText()==='事实','Wrong destination');
  assert(await page.getByText('STALE RESPONSE').count()===0,'Same-page stale response won');
  results.push({returnToSamePage:true,passed:true});
  return results;
}
