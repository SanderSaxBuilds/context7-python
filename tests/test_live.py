"""Live tests against https://context7.com/api with no API key. Skipped when CONTEXT7_OFFLINE=1."""
import os
import unittest

from context7_client import Context7, Context7Error, Docs

OFFLINE = os.environ.get("CONTEXT7_OFFLINE") == "1"


@unittest.skipIf(OFFLINE, "CONTEXT7_OFFLINE=1")
class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Context7(api_key="")

    def test_search_library(self):
        libs = self.c.search_library("build a web API with type hints", "fastapi")
        self.assertTrue(libs)
        self.assertTrue(any("fastapi" in lib.id.lower() for lib in libs))
        self.assertIsNotNone(self.c.last_rate_limit.limit)

    def test_get_context_json(self):
        lib = self.c.search_library("hooks", "react")[0]
        docs = self.c.get_context("How do I use useEffect?", lib.id)
        self.assertIsInstance(docs, Docs)
        self.assertTrue(docs.code or docs.info)

    def test_get_context_txt(self):
        lib = self.c.search_library("hooks", "react")[0]
        text = self.c.get_context("How do I use useEffect?", lib.id, type="txt")
        self.assertGreater(len(text), 200)

    def test_unknown_library(self):
        with self.assertRaises(Context7Error) as cm:
            self.c.get_context("x", "/no-such-owner-zz/no-such-lib-zz")
        self.assertEqual(cm.exception.status, 404)

    def test_search_v3(self):
        docs = self.c.search("How do I declare a dependency?", libraries=["FastAPI"])
        self.assertTrue(docs.code or docs.info)


if __name__ == "__main__":
    unittest.main()
