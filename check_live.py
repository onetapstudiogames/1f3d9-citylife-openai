"""Live checks of the ChatGPT copy against the city. Not a CI step: run it at release and in step D.

Usage: python check_live.py

Anonymous reads only: POST https://1f3d9.com/mcp/app initialize, tools/list and one front_door call,
GET https://1f3d9.com/api/tools and GET https://1f3d9.com/api/official. Nothing is written to the city.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import build

ROOT = build.ROOT
APP = build.APP
TOOLS_URL = 'https://1f3d9.com/api/tools'
OFFICIAL_URL = 'https://1f3d9.com/api/official'
TIMEOUT_SECONDS = 30
USER_AGENT = '1f3d9-citylife-openai-check/1'
SECTION_RE = re.compile(r'`front_door`\s+section\s+([a-z-]+)')


class LiveError(Exception):
    """A live read that did not answer as expected."""


def request(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'user-agent': USER_AGENT, 'accept': 'application/json, text/event-stream'}
    if data is not None:
        headers['content-type'] = 'application/json'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers),
                                    timeout=TIMEOUT_SECONDS) as answer:
            text = answer.read().decode('utf-8')
    except (urllib.error.URLError, TimeoutError) as error:
        raise LiveError('%s did not answer: %s' % (url, error)) from error
    if text.lstrip().startswith('event:') or '\ndata:' in text:
        text = ''.join(line[5:] for line in text.splitlines() if line.startswith('data:'))
    return json.loads(text)


def rpc(method: str, params: dict, ident: int) -> dict:
    answer = request(APP, {'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params})
    if 'result' not in answer:
        raise LiveError('%s answered without a result: %s' % (method, json.dumps(answer)[:300]))
    return answer['result']


def main() -> int:
    snapshot = json.loads((ROOT / 'app-door-tools.json').read_text(encoding='utf-8'))
    failed = 0

    def check(name: str, ok: bool, detail: str = '') -> None:
        nonlocal failed
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', name, (': ' + detail) if detail else ''))
        failed += 0 if ok else 1

    official = request(OFFICIAL_URL)
    print('INFO  deployment_commit %s (snapshot read at %s on %s)'
          % (official.get('deployment_commit'), snapshot['read_at'], snapshot['deployment_commit']))
    rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                       'clientInfo': {'name': USER_AGENT, 'version': '1'}}, 1)
    tools = rpc('tools/list', {}, 2)['tools']
    live = sorted(t['name'] for t in tools)
    check('live tools/list at %s equals app-door-tools.json by name' % APP, live == snapshot['tools'],
          'live only: %s; snapshot only: %s' % (sorted(set(live) - set(snapshot['tools'])),
                                                sorted(set(snapshot['tools']) - set(live))))
    count = request(TOOLS_URL).get('doors', {}).get('/mcp/app', {}).get('count')
    check('GET /api/tools doors["/mcp/app"].count equals the snapshot count', count == snapshot['count'],
          'live %s, snapshot %s' % (count, snapshot['count']))
    front_door = next((t for t in tools if t['name'] == 'front_door'), {})
    served = set(front_door.get('inputSchema', {}).get('properties', {}).get('section', {}).get('enum', []))
    index = '\n'.join(c.get('text', '') for c in rpc('tools/call', {'name': 'front_door', 'arguments': {}}, 3)
                      .get('content', []))
    texts = [p.read_text(encoding='utf-8') for p in sorted((ROOT / 'plugin').rglob('*.md'))]
    named = sorted({m for text in texts for m in SECTION_RE.findall(text)})
    missing = [s for s in named if s not in served or s not in index]
    check('every front_door section the copy names is in the app door front door index', bool(named) and not missing,
          'named %s; missing %s' % (', '.join(named), ', '.join(missing)))
    print('%s (%d failed)' % ('FAIL' if failed else 'PASS', failed))
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except LiveError as error:
        print('check_live.py could not finish: %s' % error, file=sys.stderr)
        sys.exit(2)
