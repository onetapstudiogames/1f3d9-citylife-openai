"""Offline checks of the ChatGPT copy in plugin/. CI runs these on ubuntu and windows.

Usage:
  python check.py                 check plugin/ and the repository files
  python check.py --source PATH   compare LICENSE and the icon with an existing clean clone of the tag
  python check.py --old-fixture   run the text checks on test/fixtures/published-1.9.63/; they must FAIL

Nothing here calls the city. LICENSE and the icon are compared with the git blobs at source.json's
commit, read from a clone of the generic plugin (made in a temporary folder unless --source is given).
check_live.py holds the live checks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import build

ROOT = build.ROOT
PLUGIN = ROOT / 'plugin'
FIXTURE = ROOT / 'test' / 'fixtures' / 'published-1.9.63'
TOOLS_SNAPSHOT = ROOT / 'app-door-tools.json'
APP = build.APP
COUNT = build.APP_TOOL_COUNT
SKILL_DIR = build.SKILL_DIR

# A copy of the city's APP_BANNED_TEXT, the test pattern for the app door's own served text:
# city src/door-profile.ts lines 106 to 107 at deployment_commit ad6c7441daed713b8f135020e1b20eb29ba6bddc.
# The JavaScript original is /...(?<!cannot be |never )blocked.../iu; Python needs one fixed-width
# look-behind per alternative, so that part is written (?<!cannot be )(?<!never ), which matches the same text.
APP_BANNED_TEXT = re.compile(
    r'\$\s?\d|USDC|x402|X-PAYMENT|PayPal|/buy|\bbuy|purchase|wallet|dollar|treasury|sale\b|safety'
    r'|(?<!cannot be )(?<!never )blocked|its filter', re.IGNORECASE)
# The one exact sentence APP_BANNED_TEXT lets through: the prompt of negative review case N3, which
# must ask in the user's own words for what the app cannot do. It sits only in the review cases, which
# OpenAI's reviewers read and the app door never serves.
APP_BANNED_EXEMPT = {'.codex-plugin/plugin.json': ('Buy me more fee credit.',)}

# Words the copy avoids (the owner, 2026-11-12: "don't use words like spend or money that sets off
# people's safety filters"), with their forms. The tool name `flag` in backticks is allowed.
AVOIDED = re.compile(
    r'\b(spend\w*|spent|money\w*|pay|pays|paid|paying|payment\w*|wallet\w*|buy\w*|bought|purchas\w*|cost|costs'
    r'|costing|costly|price\w*|pricing|charg\w*|cash\w*|dollar\w*|fund|funds|funded|funding|safe|safely|safety'
    r'|security|flag|flags|flagged|flagging)\b', re.IGNORECASE)
# The only sentences in plugin/ that keep an avoided word, each with the reason it stays. Exact text,
# compared with whitespace collapsed; each must be present, so the list cannot go stale.
ALLOWED_SENTENCES: dict[str, tuple[tuple[str, str], ...]] = {
    'SKILL.md': (
        ('Use when the user asks to move in, visit, make, use, upgrade, end, or withdraw things, talk, or spend '
         'approved free time."',
         'spend is about time, not fee credit; the owner has not answered plan question 7 (b)'),
    ),
    'references/resident-guide.md': (
        ('Fee credit is used for city fees; it cannot be transferred or cashed out.',
         'the generic 1.9.69 wording (word-pass C1, short form), ported unchanged; the city terms say credit '
         'cannot be cashed out, and dropping the words drops the meaning'),
        ('Anonymous flagging remains web-only.',
         'flagging is the act of the `flag` tool, not money; plan question 7 (b) is not answered'),
        ('**Flag carefully:** flag genuinely unlawful or prohibited content, never disagreement; the flag is '
         'public and the flag event names the reporter.',
         'flag here is the `flag` tool and its public event, not money; plan question 7 (b) is not answered'),
        ('An end is `{"any": [...]}` with 1 to 4 conditions, each a different way: `{"at": '
         '"2026-12-31T00:00:00.000Z"}`, `{"after_setting_seconds": 86400}`, `{"uses": 50}`, `{"idle_seconds": '
         '604800}` or `{"label_added": "spent"}`.',
         'a fixed name: "spent" is the example label value inside a JSON end object'),
        ('Ordinary tales may earn platform ad revenue; paid advertisements and sponsored promotions require '
         'separate permission.',
         'real advertising outside the city, in the words of the city media rule (official_facts '
         'public_content_retelling); not fee credit'),
        ('A retry is safe and creates no public event or change notice.',
         'safe is not a money word; plan question 7 (b) is not answered'),
    ),
    'references/public-reading.md': (
        ('Keep `q` to one safe line and at most 256 UTF-8 bytes.',
         'safe is not a money word; plan question 7 (b) is not answered'),
    ),
    '.codex-plugin/plugin.json': (
        ('Buy me more fee credit.',
         'the prompt of negative review case N3, which tests that the app refuses what it cannot do'),
    ),
}
LISTING_FIELDS = ('shortDescription', 'longDescription', 'defaultPrompt')
NAMED_ONLY_IN_ITS_OWN_DESCRIPTION = ('credit_gift',)
FULL_DOOR_ONLY = ('buy_credit', 'payment_attempt', 'list_world', 'claim_world', 'cancel_world', 'reconcile_world')
NEVER_NAMED = FULL_DOOR_ONLY + NAMED_ONLY_IN_ITS_OWN_DESCRIPTION
# Plugin commands this copy does not carry, as they would be written in backticks.
COMMANDS = ('join', 'setup', 'connect', 'donate', 'buy', 'schedule', 'follow', 'update', 'changelog', 'tools')
COMMAND_FORMS = re.compile(r'/1f3d9-citylife:|connect chat|key (status|rotate|recover|show|adopt)|--reveal'
                           r'|--new-identity|run `[a-z]+`|`links` command|`help` command')
BANNED_PATHS = ('/mcp/connect', '1f3d9-local', 'localhost', '1f3ea.com', '/window', '/api/', '/join', '/buy')
SCHEMA_PREFIX = 'https://agent-plugins.org/schemas/'
HUMAN_PAGES = ('https://1f3d9.com/recovery', 'https://1f3d9.com/rotate')
MANIFEST_LINKS = ('https://1f3d9.com', 'https://1f3d9.com/privacy', 'https://1f3d9.com/terms',
                  'https://1f3d9.com/support')
URL_RE = re.compile(r'https?://[^\s)`"\'<>,;]+')
PUNCT_RE = re.compile('[–—‘’“”]')
# Markers that the guide is today's text and not the 1.9.42 text the listing carries.
FRESH_MARKERS = ('### Things that end', '### What an action answers, and retrying one', '### Last-active bands',
                 '### Recovery codes and a lost key')
STALE_MARKER = 'neither outline'
GIFT_SENTENCES = (
    'For each ordinary pending gift listed by `me`, the resident may accept it, refuse it, or leave it pending.',
    'Fee-credit gifts: `me` lists them, and each can be accepted or refused.',
)
TEXT_FILES = build.TEXT_PAIRS


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = '') -> None:
        self.lines.append('%s  %s%s' % ('PASS' if ok else 'FAIL', name, (': ' + detail) if detail and not ok else ''))
        self.failed += 0 if ok else 1


def flat(text: str) -> str:
    return re.sub(r'\s+', ' ', text)


def read_texts(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    return {name: (root / name).read_text(encoding='utf-8') for name in names if (root / name).is_file()}


# ===================================================================================== text checks

def expected_headings(name: str) -> list[str]:
    table = build.HEADINGS[name]
    kept = [h for h, v in table.items() if v[0] == 'keep'] + [v[1] for v in table.values() if v[0] == 'reword']
    return sorted(kept + list(build.ADDED_HEADINGS.get(name, ())))


def check_text_rules(report: Report, texts: dict[str, str]) -> None:
    """The rules for the skill and its two references; --old-fixture runs only these."""
    for name in TEXT_FILES:
        report.check('%s exists' % name, name in texts)
    for name, body in texts.items():
        found = sorted(build.headings(body))
        report.check('heading list of %s is the classified list' % name, found == expected_headings(name),
                     'unexpected %s; missing %s' % (sorted(set(found) - set(expected_headings(name))),
                                                    sorted(set(expected_headings(name)) - set(found))))
    joined = '\n'.join(texts.values())
    counts = [int(n) for n in re.findall(r'\b(\d+)[ -]tools?\b', joined)]
    report.check('every stated tool count is %d' % COUNT, bool(counts) and all(n == COUNT for n in counts),
                 ', '.join(map(str, counts)))
    guide = texts.get('references/resident-guide.md', '')
    for marker in FRESH_MARKERS:
        report.check('the guide has the section %r' % marker, marker in guide)
    report.check('the guide has no %r sentence' % STALE_MARKER, STALE_MARKER not in flat(joined))
    for sentence in GIFT_SENTENCES:
        report.check('the guide says %r' % sentence[:60], sentence in flat(guide))
    check_words(report, texts)
    check_addresses(report, texts)
    check_tool_names(report, texts)
    check_links(report, texts)


def without_allowed(name: str, body: str, report: Report) -> str:
    text = flat(body)
    base = name[len(SKILL_DIR):] if name.startswith(SKILL_DIR) else name
    for sentence, _reason in ALLOWED_SENTENCES.get(base, ()):
        report.check('allowed sentence is present in %s: %r' % (name, sentence[:50]), sentence in text)
        text = text.replace(sentence, ' ')
    return text.replace('`flag`', ' ')


def check_words(report: Report, texts: dict[str, str]) -> None:
    for name, body in texts.items():
        rest = without_allowed(name, body, report)
        hits = sorted({m.group(0) for m in AVOIDED.finditer(rest)})
        report.check('no avoided word in %s outside the exact allow list' % name, not hits, ', '.join(hits))
        exempt = APP_BANNED_EXEMPT.get(name, ())
        served = flat(body)
        for sentence in exempt:
            served = served.replace(sentence, ' ')
        banned = sorted({m.group(0) for m in APP_BANNED_TEXT.finditer(served)})
        report.check('zero APP_BANNED_TEXT hits in %s' % name, not banned, ', '.join(banned))
        punct = PUNCT_RE.findall(body)
        report.check('no em dash, en dash or curly quote in %s' % name, not punct, repr(punct[:5]))
        report.check('no Claude wording in %s' % name, 'claude' not in body.lower())
        report.check('no reviewer_instructions or test_credentials in %s' % name,
                     'reviewer_instructions' not in body and 'test_credentials' not in body)
        if name != '.codex-plugin/plugin.json':
            report.check('smokecheck is not named in %s' % name, 'smokecheck' not in body.lower())


def allowed_urls(name: str) -> set[str]:
    urls = {APP, *HUMAN_PAGES}
    if name.endswith('.json'):
        urls |= {*MANIFEST_LINKS, build.COPY_REPOSITORY}
    return urls


def check_addresses(report: Report, texts: dict[str, str]) -> None:
    for name, body in texts.items():
        urls = {u.rstrip('.:') for u in URL_RE.findall(body)}
        schema_ok = name in ('plugin.json', 'mcp.json')
        bad = sorted(u for u in urls if u not in allowed_urls(name) and not (schema_ok and u.startswith(SCHEMA_PREFIX)))
        report.check('every web address in %s is on the allow list' % name, not bad, ' '.join(bad))
        no_urls = URL_RE.sub(' ', body)
        paths = [p for p in BANNED_PATHS if p in body.lower()]
        bare = re.findall(r'/mcp(?!/app)\b', no_urls) + re.findall(r'1f3d9\.com/mcp(?!/app)', body)
        report.check('no other door, bridge, route or page in %s' % name, not paths and not bare,
                     ' '.join(paths + bare))
        domains = len(re.findall(r'1f3d9\.com', no_urls.replace('adam@twamd.com', '')))
        listing = 1 if name == '.codex-plugin/plugin.json' else 0
        report.check('the bare words 1f3d9.com appear only in the listing sentence (%s)' % name, domains == listing,
                     '%d found' % domains)


def check_tool_names(report: Report, texts: dict[str, str]) -> None:
    snapshot = set(json.loads(TOOLS_SNAPSHOT.read_text(encoding='utf-8'))['tools'])
    city_tools = snapshot | set(FULL_DOOR_ONLY) | {'moderate'}
    for name, body in texts.items():
        ticked = set(re.findall(r'`([a-z][a-z0-9_]*)`', body))
        outside = sorted(t for t in ticked if t in city_tools and t not in snapshot and t != 'moderate')
        report.check('every backticked city tool in %s is in app-door-tools.json' % name, not outside, ', '.join(outside))
        named = [t for t in NEVER_NAMED if t in body]
        report.check('%s never names %s' % (name, ', '.join(NEVER_NAMED)), not named, ', '.join(named))
        moderate = flat(body).count('`moderate`')
        omitted = flat(body).count('omits founder-only `moderate`')
        report.check('`moderate` only as the founder-only tool this door omits (%s)' % name, moderate == omitted)
        commands = sorted(c for c in COMMANDS if c in ticked)
        forms = [m.group(0) for m in COMMAND_FORMS.finditer(body)]
        report.check('no plugin command named in %s' % name, not commands and not forms, ', '.join(commands + forms))


def anchor_of(heading: str) -> str:
    return re.sub(r'[^a-z0-9 -]', '', heading.lstrip('#').strip().lower()).replace(' ', '-')


def check_links(report: Report, texts: dict[str, str]) -> None:
    for name, body in texts.items():
        for target in re.findall(r'\]\(([^)]+)\)', body):
            if re.match(r'^[a-z]+://', target) or target.startswith('#'):
                continue
            file, _, anchor = target.partition('#')
            path = (Path(name).parent / file).as_posix()
            ok = path in texts and (not anchor or anchor in {anchor_of(h) for h in build.headings(texts[path])})
            report.check('local link resolves: %s -> %s' % (name, target), ok)


# ================================================================================= package checks

def check_files(report: Report) -> dict[str, bytes]:
    files = build.tree(PLUGIN)
    report.check('plugin/ holds exactly the 14 listed files', tuple(sorted(files)) == build.PLUGIN_FILES,
                 ', '.join(sorted(set(files) ^ set(build.PLUGIN_FILES))))
    for name in TEXT_FILES:
        report.check('%s equals %s byte for byte' % (name, SKILL_DIR + name),
                     name in files and files.get(name) == files.get(SKILL_DIR + name))
    for name, body in files.items():
        if not name.endswith('.png'):
            report.check('%s is LF only' % name, b'\r' not in body)
    return files


def check_manifests(report: Report, files: dict[str, bytes], source: dict) -> None:
    load = lambda name: json.loads(files[name].decode('utf-8'))  # noqa: E731
    root, codex, claude = load('plugin.json'), load('.codex-plugin/plugin.json'), load('.claude-plugin/plugin.json')
    version = source['version']
    report.check('one version, %s, in the three manifests' % version,
                 root['version'] == codex['version'] == claude['version'] == version)
    changelog = files['CHANGELOG.md'].decode('utf-8')
    report.check('plugin/CHANGELOG.md equals the root CHANGELOG.md', files['CHANGELOG.md'] == build.CHANGELOG.read_bytes())
    tops = re.findall(r'^## (\S+)', changelog, re.MULTILINE)
    report.check('CHANGELOG starts at %s and keeps 1.9.63 and 1.9.42' % version,
                 tops[:1] == [version] and '1.9.63' in tops and '1.9.42' in tops, ', '.join(tops))
    report.check('CHANGELOG says it is cut from the generic commit',
                 'commit %s' % source['commit'][:7] in changelog and '37 tools' in changelog)
    report.check('root plugin.json author is TWAMD LLC and it has no extensions',
                 root.get('author') == {'name': build.DEVELOPER} and 'extensions' not in root)
    for label, manifest in (('codex', codex), ('claude', claude)):
        report.check('%s author is TWAMD LLC with adam@twamd.com' % label, manifest.get('author') == build.AUTHOR)
        report.check('%s repository is this copy' % label, manifest.get('repository') == build.COPY_REPOSITORY)
        report.check('%s keywords' % label, manifest.get('keywords') == build.KEYWORDS)
        report.check('%s has no skills, hooks, commands or agents' % label,
                     not any(k in manifest for k in ('skills', 'hooks', 'commands', 'agents', 'mcpServers')))
    names = [v for k, v in walk_pairs(root) + walk_pairs(codex) + walk_pairs(claude)
             if k in ('developerName', 'publisher', 'owner') or (k == 'name' and v not in ('1f3d9-citylife', '1f3d9'))]
    report.check('TWAMD LLC wherever a developer or author is named', names and all(n == build.DEVELOPER for n in names),
                 ', '.join(map(str, names)))
    check_interface(report, codex['interface'], version)
    check_extensions(report, codex.get('extensions', {}), version)
    report.check('mcp.json is the one app-door server', load('mcp.json') == build.mcp_manifest(with_schema=True))
    report.check('.mcp.json is the one app-door server', load('.mcp.json') == build.mcp_manifest(with_schema=False))


def walk_pairs(node: object) -> list[tuple[str, object]]:
    if isinstance(node, dict):
        return [(k, v) for k, v in node.items() if not isinstance(v, (dict, list))] + \
            [p for v in node.values() for p in walk_pairs(v)]
    if isinstance(node, list):
        return [p for v in node for p in walk_pairs(v)]
    return []


def check_interface(report: Report, interface: dict, version: str) -> None:
    report.check('developerName is TWAMD LLC', interface.get('developerName') == build.DEVELOPER)
    report.check('longDescription names the city website', interface.get('longDescription') == build.LONG_DESCRIPTION)
    report.check('defaultPrompt', interface.get('defaultPrompt') == build.DEFAULT_PROMPT)
    report.check('category Entertainment', interface.get('category') == 'Entertainment')
    report.check('icons point at the packaged icon', interface.get('composerIcon') == build.ICON == interface.get('logo'))
    report.check('the four listing links', [interface.get(k) for k in ('websiteURL', 'privacyPolicyURL',
                 'termsOfServiceURL', 'supportURL')] == list(MANIFEST_LINKS))
    for field in LISTING_FIELDS:
        value = json.dumps(interface.get(field))
        hits = AVOIDED.findall(value) + APP_BANNED_TEXT.findall(value) + PUNCT_RE.findall(value)
        report.check('listing field %s has no avoided word or dash' % field, not hits, ', '.join(hits))
    report.check('shortDescription is at most 30 characters', len(interface.get('shortDescription', '')) <= 30)


def check_extensions(report: Report, extensions: dict, version: str) -> None:
    report.check('extensions has only "com.openai"', list(extensions) == ['com.openai'])
    openai = extensions.get('com.openai', {})
    notes = openai.get('publication', {}).get('release_notes', '')
    report.check('release notes', notes == build.RELEASE_NOTES.format(version=version))
    hits = AVOIDED.findall(notes) + APP_BANNED_TEXT.findall(notes) + PUNCT_RE.findall(notes)
    report.check('release notes have no avoided word, dash, or gift claim', not hits and 'gift' not in notes.lower())
    review = openai.get('review', {})
    report.check('no demo_recording_url in the package (the saved one is kept)', 'demo_recording_url' not in review)
    cases = review.get('test_cases', {})
    report.check('review cases equal review-cases.json', cases == json.loads(build.REVIEW_CASES.read_text(encoding='utf-8')))
    check_cases(report, cases)


def check_cases(report: Report, cases: dict) -> None:
    positive, negative = cases.get('positive', []), cases.get('negative', [])
    report.check('5 positive and 3 negative cases', len(positive) == 5 and len(negative) == 3)
    report.check('positive cases have exactly description, prompt, tools_triggered, expected_behavior',
                 all(set(c) == {'description', 'prompt', 'tools_triggered', 'expected_behavior'} for c in positive))
    report.check('negative cases have exactly description and prompt', all(set(c) == {'description', 'prompt'} for c in negative))
    values = [v for c in positive + negative for v in c.values()]
    report.check('every case field is one non-empty line', all(isinstance(v, str) and v.strip() and '\n' not in v for v in values))
    report.check('every case description is at most 200 characters', all(len(c['description']) <= 200 for c in positive + negative))
    snapshot = set(json.loads(TOOLS_SNAPSHOT.read_text(encoding='utf-8'))['tools'])
    triggered = {t for c in positive for t in re.findall(r'[a-z][a-z_]+', c['tools_triggered']) if '_' in t or t in snapshot}
    report.check('every tools_triggered name is in app-door-tools.json', triggered <= snapshot, ', '.join(sorted(triggered - snapshot)))
    report.check('negative case N1 uses the sign-in page title', '"Let this chat enter 1F3D9?"' in negative[0]['description'])


def check_snapshot(report: Report) -> None:
    data = json.loads(TOOLS_SNAPSHOT.read_text(encoding='utf-8'))
    report.check('app-door-tools.json has the documented keys',
                 list(data) == ['read_at', 'source', 'deployment_commit', 'count', 'tools'])
    report.check('app-door-tools.json source', data.get('source') == 'POST %s tools/list, anonymous' % APP)
    report.check('app-door-tools.json deployment_commit is a full sha',
                 bool(re.fullmatch(r'[0-9a-f]{40}', data.get('deployment_commit', ''))))
    tools = data.get('tools', [])
    report.check('app-door-tools.json lists %d sorted unique names' % COUNT,
                 data.get('count') == COUNT == len(tools) and tools == sorted(set(tools)))


def check_blobs(report: Report, files: dict[str, bytes], source: dict, source_path: Path | None) -> None:
    with tempfile.TemporaryDirectory(prefix='1f3d9-openai-check-') as temp:
        clone = source_path.resolve() if source_path else build.clone_source(source, Path(temp))
        build.check_source(clone, source)
        for name in ('LICENSE', 'assets/1f3d9-512.png'):
            report.check('%s is byte-identical to the git blob at %s' % (name, source['commit'][:7]),
                         files.get(name) == build.blob(clone, source['commit'], name))
        report.check('the root LICENSE is byte-identical to the git blob at %s' % source['commit'][:7],
                     (ROOT / 'LICENSE').read_bytes() == build.blob(clone, source['commit'], 'LICENSE'))
    png = files.get('assets/1f3d9-512.png', b'')
    report.check('icon is a 512 by 512 PNG', png[:8] == b'\x89PNG\r\n\x1a\n'
                 and int.from_bytes(png[16:20], 'big') == 512 and int.from_bytes(png[20:24], 'big') == 512)


def check_repository(report: Report) -> None:
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    report.check('README has no avoided word', not AVOIDED.findall(readme), ', '.join(AVOIDED.findall(readme)))
    for name in ('README.md', 'AGENTS.md', 'CLAUDE.md', 'CHANGELOG.md', 'source.json', 'review-cases.json'):
        body = (ROOT / name).read_text(encoding='utf-8')
        report.check('no em dash, en dash or curly quote in %s' % name, not PUNCT_RE.findall(body))
        report.check('%s does not link the Claude copy' % name, 'citylife-hosted' not in body)
        report.check('%s carries no reviewer field' % name,
                     'reviewer_instructions' not in body and 'test_credentials' not in body)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Offline checks of the ChatGPT copy.')
    parser.add_argument('--source', type=Path, help='an existing clean clone of the generic plugin at the tag')
    parser.add_argument('--old-fixture', action='store_true', help='run the text checks on the published 1.9.63 text')
    args = parser.parse_args(argv)
    report = Report()
    if args.old_fixture:
        check_text_rules(report, read_texts(FIXTURE, TEXT_FILES))
    else:
        source = build.load_source_json()
        files = check_files(report)
        texts = {n: b.decode('utf-8') for n, b in files.items() if not n.endswith('.png') and n != 'LICENSE'}
        check_text_rules(report, {n: texts[n] for n in TEXT_FILES if n in texts})
        others = {n: t for n, t in texts.items() if n not in TEXT_FILES}
        check_words(report, others)
        check_addresses(report, others)
        check_tool_names(report, others)
        check_manifests(report, files, source)
        check_snapshot(report)
        check_repository(report)
        check_blobs(report, files, source, args.source)
    print('\n'.join(report.lines))
    print('%s (%d failed of %d)' % ('FAIL' if report.failed else 'PASS', report.failed, len(report.lines)))
    return 1 if report.failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except build.BuildError as error:
        print('check.py refused: %s' % error, file=sys.stderr)
        sys.exit(2)
