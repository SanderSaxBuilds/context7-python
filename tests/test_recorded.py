"""Offline tests. Every fixture is a real Context7 answer recorded on 13 Nov 2026, trimmed for size."""
import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from context7_client import Context7, Context7Error, Docs

FIX = Path(__file__).parent / "fixtures"


def fixture(name):
    d = json.loads((FIX / name).read_text(encoding="utf-8"))
    return d["status"], d["headers"], d["body"]


class Recorder:
    """Fake transport that answers with fixtures in order and keeps the requests."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, headers))
        a = self.answers.pop(0)
        return fixture(a) if isinstance(a, str) else a


def query(url):
    return {k: v if len(v) > 1 else v[0] for k, v in parse_qs(urlparse(url).query).items()}


class SearchLibraryTests(unittest.TestCase):
    def test_parses_results(self):
        t = Recorder("search_library_fastapi.json")
        libs = Context7(api_key="", transport=t).search_library("dependency injection", "fastapi")
        self.assertEqual(len(libs), 2)
        self.assertEqual(libs[0].id, "/websites/fastapi_tiangolo")
        self.assertEqual(libs[0].title, "FastAPI")
        self.assertGreater(libs[0].total_snippets, 0)
        self.assertIsNone(libs[0].stars)  # API sends -1 for "unknown"
        q = query(t.calls[0][1])
        self.assertEqual(q, {"libraryName": "fastapi", "query": "dependency injection"})
        self.assertTrue(t.calls[0][1].startswith("https://context7.com/api/v2/libs/search?"))

    def test_no_results_is_empty_list(self):
        t = Recorder("search_library_none.json")
        self.assertEqual(Context7(api_key="", transport=t).search_library("x", "zzzzqqqxnotreal"), [])

    def test_rate_limit_headers_are_kept(self):
        c = Context7(api_key="", transport=Recorder("search_library_fastapi.json"))
        c.search_library("q", "fastapi")
        self.assertEqual(c.last_rate_limit.limit, 200)
        self.assertIsNotNone(c.last_rate_limit.remaining)


class GetContextTests(unittest.TestCase):
    def test_json_docs(self):
        t = Recorder("context_json.json")
        docs = Context7(api_key="", transport=t).get_context("dependency injection", "/websites/fastapi_tiangolo")
        self.assertIsInstance(docs, Docs)
        self.assertEqual(len(docs.code), 1)
        self.assertIn("Depends", docs.code[0].title)
        self.assertTrue(docs.code[0].source.startswith("https://fastapi.tiangolo.com/"))
        self.assertEqual(len(docs.info), 1)
        self.assertGreater(docs.tokens, 0)
        self.assertIsNone(docs.redirected_from)

    def test_follows_library_redirect(self):
        t = Recorder("context_redirect.json", "context_json.json")
        docs = Context7(api_key="", transport=t).get_context("dependency injection", "/fastapi/fastapi")
        self.assertEqual(docs.redirected_from, "/fastapi/fastapi")
        self.assertEqual(docs.library_id, "/websites/fastapi_tiangolo")
        self.assertEqual(query(t.calls[1][1])["libraryId"], "/websites/fastapi_tiangolo")

    def test_redirect_can_be_raised(self):
        t = Recorder("context_redirect.json")
        with self.assertRaises(Context7Error) as cm:
            Context7(api_key="", transport=t).get_context("q", "/fastapi/fastapi", follow_redirects=False)
        self.assertEqual(cm.exception.code, "library_redirected")

    def test_txt(self):
        t = Recorder("context_txt.json")
        text = Context7(api_key="", transport=t).get_context("dependency injection", "/websites/fastapi_tiangolo", type="txt")
        self.assertIsInstance(text, str)
        self.assertIn("Dependency Injection", text)
        self.assertEqual(query(t.calls[0][1])["type"], "txt")

    def test_not_found_raises(self):
        with self.assertRaises(Context7Error) as cm:
            Context7(api_key="", transport=Recorder("context_not_found.json")).get_context("x", "/nope/nope")
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(cm.exception.code, "library_not_found")

    def test_bad_type(self):
        with self.assertRaises(ValueError):
            Context7(api_key="").get_context("q", "/a/b", type="xml")


class TransportTests(unittest.TestCase):
    def test_retries_429_then_succeeds(self):
        slept = []
        t = Recorder((429, {"Retry-After": "1"}, '{"error":"rate_limited","message":"slow down"}'),
                     "search_library_fastapi.json")
        libs = Context7(api_key="", transport=t, sleep=slept.append).search_library("q", "fastapi")
        self.assertEqual(len(libs), 2)
        self.assertEqual(len(t.calls), 2)
        self.assertEqual(slept, [1.0])

    def test_gives_up_after_retries(self):
        t = Recorder(*[(503, {}, "")] * 3)
        with self.assertRaises(Context7Error) as cm:
            Context7(api_key="", transport=t, retries=2, sleep=lambda s: None).search_library("q", "x")
        self.assertEqual(cm.exception.status, 503)
        self.assertEqual(len(t.calls), 3)

    def test_api_key_header(self):
        t = Recorder("search_library_fastapi.json")
        Context7(api_key="ctx7sk-test", transport=t).search_library("q", "fastapi")
        self.assertEqual(t.calls[0][2]["Authorization"], "Bearer ctx7sk-test")

    def test_no_key_no_header(self):
        t = Recorder("search_library_fastapi.json")
        Context7(api_key="", transport=t).search_library("q", "fastapi")
        self.assertNotIn("Authorization", t.calls[0][2])

    def test_search_params(self):
        t = Recorder("context_json.json")
        Context7(api_key="", transport=t).search("cache a function", libraries=["Next.js"], version="15.4.0",
                                                 language="TypeScript")
        q = query(t.calls[0][1])
        self.assertEqual(q["library"], "Next.js")
        self.assertEqual(q["version"], "15.4.0")
        self.assertTrue(t.calls[0][1].startswith("https://context7.com/api/v3/search?"))

    def test_search_checks_arguments(self):
        c = Context7(api_key="")
        with self.assertRaises(ValueError):
            c.search("q", version="1.0")
        with self.assertRaises(ValueError):
            c.search("q", libraries=["a", "b", "c", "d", "e"])


if __name__ == "__main__":
    unittest.main()
