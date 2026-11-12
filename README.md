# context7-python

A small Python client for the [Context7](https://context7.com) API. It covers library search, documentation context (JSON or plain text) and the one-call v3 search, with the same method names as the official TypeScript SDK `@upstash/context7-sdk`.

Standard library only, Python 3.9 and up. Works without an API key at the anonymous rate limit, or with a key for the higher one.

Community package, not published or supported by Upstash.

## Quickstart

```bash
pip install git+https://github.com/SanderSaxBuilds/context7-python
```

```python
from context7_client import Context7

c7 = Context7()  # reads CONTEXT7_API_KEY if set, otherwise runs keyless

libs = c7.search_library("build a web API with type hints", "fastapi")
print(libs[0].id, libs[0].total_snippets)        # /websites/fastapi_tiangolo 4160

docs = c7.get_context("dependency injection", libs[0].id)
for snippet in docs.code:
    print(snippet.title, snippet.source)

text = c7.get_context("dependency injection", libs[0].id, type="txt")  # ready to paste into a prompt

hits = c7.search("How do I cache a function?", libraries=["Next.js"], version="15.4.0")
print(c7.last_rate_limit)                         # RateLimit(limit=200, remaining=..., reset=...)
```

`examples/prompt_context.py` builds a prompt block for a question about any library:

```bash
python examples/prompt_context.py fastapi "How do I add a dependency to every route?"
```

## What it handles

| Case | Behaviour |
|---|---|
| Library ID moved (`library_redirected`, HTTP 301) | Follows `redirectUrl` once and sets `docs.redirected_from`. Pass `follow_redirects=False` to get a `Context7Error` instead |
| No library matches | `search_library` returns `[]` |
| Unknown library ID | `Context7Error` with `status=404`, `code="library_not_found"` |
| 408, 425, 429, 5xx, network errors | Retries with exponential backoff, honours `Retry-After` (2 retries by default) |
| Rate limit headers | Kept on `client.last_rate_limit` and on every `Context7Error` |
| API key | `Authorization: Bearer` only when a key is given |

Custom HTTP is one function: pass `transport=` with the signature `(method, url, headers, timeout) -> (status, headers, body)`. The tests use this to replay recorded answers.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

- `tests/test_recorded.py`, 15 tests on real Context7 answers recorded on 13 Nov 2026 (trimmed), no network.
- `tests/test_live.py`, 5 tests against the live API with no key. Set `CONTEXT7_OFFLINE=1` to skip them.

Last run, 13 Nov 2026: 20 passed, 0 failed.

## License

MIT
