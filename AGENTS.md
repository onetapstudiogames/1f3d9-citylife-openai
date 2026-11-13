# 1f3d9-citylife-openai: working standard

This repository holds the ChatGPT directory copy of the city plugin and the script that builds it.

- `plugin/` and `dist.sha256` are build output. Never edit them by hand: change `build.py`, `review-cases.json`, `CHANGELOG.md` or `source.json`, then run `python build.py`.
- A new version means pointing `source.json` at a newer tag of https://github.com/onetapstudiogames/1f3d9-citylife and rebuilding. The copy's version is always the generic version it was cut from, and its CHANGELOG entry says so.
- Every source heading is listed in `build.py` as keep, drop or reword, and every edit must match its source text exactly once; a refusal means the generic text moved, so update the edit, never loosen the check.
- `app-door-tools.json` is a dated reading of the live app address; refresh it with a new anonymous `tools/list` and record the `deployment_commit`.
- Nothing private goes here: no portal notes, screenshots, reviewer fields, keys, test credentials or recordings.
- No em dashes, en dashes or curly quotes. Commits are "type: description" with no trailers.
- CI "checks" must be green before a merge: `python build.py --verify`, `python check.py` and the old-fixture check on ubuntu and windows. Run `python check_live.py` at release.
