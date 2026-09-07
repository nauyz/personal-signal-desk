"""Read-only public-page probe. Never uses tokens or prints response bodies."""
import json
import re
import urllib.request
import urllib.error
import server

for page in (1, 2):
    url = server.producthunt_category_url('productivity', page)
    result = {'url': url}
    try:
        request = urllib.request.Request(url, headers={'Accept':'text/html','User-Agent':server.USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode('utf-8', errors='replace')
            result.update(status=response.status, bytes=len(body), jsonld=len(re.findall('application/ld',body)))
            try:
                result['products'] = len(server.parse_producthunt_category_page(body))
            except Exception as exc:
                result['parse_error'] = str(exc)
    except urllib.error.HTTPError as exc:
        result.update(status=exc.code, mitigation=exc.headers.get('cf-mitigated'))
    except Exception as exc:
        result.update(error=type(exc).__name__, detail=str(exc)[:200])
    print(json.dumps(result,ensure_ascii=False), flush=True)
