const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const dist = path.join(root, 'dist');
const output = path.join(root, 'test-artifacts');
fs.mkdirSync(output, {recursive:true});
const server = http.createServer((req,res) => {
  const relative = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const file = path.resolve(dist, '.' + (relative === '/' ? '/index.html' : relative));
  if (!file.startsWith(dist + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (err,data) => {
    if (err) {res.writeHead(404).end();return;}
    const type = {'.html':'text/html','.js':'application/javascript','.json':'application/json','.css':'text/css'}[path.extname(file)];
    res.setHeader('Content-Type', (type || 'application/octet-stream') + '; charset=utf-8');
    res.end(data);
  });
});
(async () => {
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || undefined});
  const reports = [];
  process.chdir(output);
  try {
    for (const test of ['search-browser','navigation-browser']) {
      const context = await browser.newContext();
      await context.tracing.start({screenshots:true,snapshots:true});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror',e=>errors.push(e.message));
      try {
        const source = fs.readFileSync(path.join(root,'tests',test+'.js'),'utf8').replaceAll('http://127.0.0.1:8876',base);
        const result = await vm.runInThisContext('('+source+')')(page);
        if (errors.length) throw Error(errors.join('\n'));
        reports.push({test,status:'passed',result});
        console.log('PASS',test,JSON.stringify(result));
      } catch (error) {
        reports.push({test,status:'failed',error:error.message});
        await page.screenshot({path:path.join(output,test+'-failure.png')}).catch(()=>{});
        throw error;
      } finally {
        await context.tracing.stop({path:path.join(output,test+'.zip')});
        await context.close();
      }
    }
  } finally {
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(reports,null,2));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.close());
