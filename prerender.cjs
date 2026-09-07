// Reuse the actual frontend markup; no browser, network, or third-party modules.
const fs = require('node:fs');
const vm = require('node:vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const node = {innerHTML: payload.emptyHTML};
const context = vm.createContext({
  URL, URLSearchParams, Intl,
  location: {pathname: '/content', search: ''},
  document: {querySelector: () => node, addEventListener() {}},
  window: {PRERENDER: true, addEventListener() {}},
  payload,
});
vm.runInContext(fs.readFileSync(payload.script, 'utf8'), context);
const markup = vm.runInContext('contentPageHTML(payload.data, getContentState())', context);
process.stdout.write(markup.replace(/<(button|input)\b/g, '<$1 disabled')
  .replace('placeholder="搜索标题、摘要或信源"', 'placeholder="搜索准备中，可先阅读下方内容"'));
