"""Regression coverage for real Graph URL construction (feature 002).

The rest of the offline suite patches the single ``_http`` seam, so it asserts *which* ``(method, url)``
a verb intends to call but never feeds the URL to ``urllib``/``http.client`` — which is exactly where
URL validation lives. That gap let a raw space in ``$orderby=receivedDateTime desc`` pass 25/25 tests
yet raise ``http.client.InvalidURL`` on first live use.

These tests close the gap: they build each verb's *real* URL (through ``_graph_url`` and through the
verbs themselves, capturing what they hand to ``_http``) and assert ``urllib.request.Request`` accepts
it — no network, no mailbox. A reintroduced space anywhere in a query string fails here.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "plugin" / "src"))

import msgraph.client as client  # noqa: E402


def _assert_valid_url(testcase: unittest.TestCase, url: str) -> None:
    """A URL is valid iff it has no raw space/control char and urllib accepts it."""
    for ch in url:
        if ch == " " or ord(ch) < 0x20 or ord(ch) == 0x7F:
            testcase.fail(f"URL contains illegal raw character {ch!r}: {url!r}")
    try:
        req = urllib.request.Request(url)
        # Force the parsing that raised InvalidURL on the live run.
        _ = req.full_url
        _ = req.host
    except Exception as exc:  # noqa: BLE001 — any construction failure is a regression
        testcase.fail(f"urllib.request.Request rejected URL {url!r}: {exc}")


class GraphUrlContractTest(unittest.TestCase):
    """Direct checks of the _graph_url helper (the single construction seam)."""

    def test_space_in_value_is_percent_encoded(self):
        url = client._graph_url("/me/messages", {"$orderby": "receivedDateTime desc"})
        self.assertIn("receivedDateTime%20desc", url)
        self.assertNotIn("receivedDateTime desc", url)
        _assert_valid_url(self, url)

    def test_dollar_and_comma_stay_literal(self):
        url = client._graph_url("/me/messages", {"$top": 10, "$select": "id,subject,from"})
        self.assertIn("$top=10", url)
        self.assertIn("$select=id,subject,from", url)
        _assert_valid_url(self, url)

    def test_no_params_has_no_query(self):
        url = client._graph_url("/me/mailFolders/inbox/messageRules")
        self.assertEqual(url, f"{client.GRAPH}/me/mailFolders/inbox/messageRules")
        _assert_valid_url(self, url)

    def test_the_exact_defect_url_is_now_valid(self):
        # The literal query that crashed the first live run.
        url = client._graph_url(
            "/me/messages",
            {"$top": 10, "$select": "id,subject,from,receivedDateTime", "$orderby": "receivedDateTime desc"},
        )
        _assert_valid_url(self, url)


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class VerbUrlConstructionTest(unittest.TestCase):
    """Drive each read/verify verb and validate the URL it actually hands to _http."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = (client.STATE_DIR, client.TOKEN_PATH, client.MARKER_PATH, client._http)
        client.STATE_DIR = tmp
        client.TOKEN_PATH = tmp / "token.json"
        client.MARKER_PATH = tmp / "verifications.json"
        client.save_token(
            {
                "access_token": "fake-access",
                "refresh_token": "fake-refresh",
                "scope": (
                    "Mail.Read Mail.ReadWrite MailboxSettings.Read "
                    "MailboxSettings.ReadWrite offline_access"
                ),
                "expires_at": time.time() + 3600,
            }
        )
        self.urls: list[str] = []

        def capture(method, url, token=None, body=None, form=False):
            self.urls.append(url)
            return {"value": []}

        client._http = capture

    def tearDown(self):
        client.STATE_DIR, client.TOKEN_PATH, client.MARKER_PATH, client._http = self._orig
        self._tmp.cleanup()

    def _run(self, fn, args):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            fn(args)

    def test_mail_list_url_is_valid(self):
        self._run(client.cmd_mail_list, _Args(limit=10, format="concise"))
        self.assertTrue(self.urls)
        for url in self.urls:
            _assert_valid_url(self, url)

    def test_rule_verify_fetch_url_is_valid(self):
        self._run(client.cmd_rule_verify, _Args(header_contains=["List-Unsubscribe"], format="concise"))
        self.assertTrue(self.urls)
        for url in self.urls:
            _assert_valid_url(self, url)

    def test_mail_get_url_with_awkward_id_is_valid(self):
        # Graph message ids are opaque and can contain path-unsafe characters.
        self._run(
            client.cmd_mail_get,
            _Args(message_id="AAMk=ADk/+ id", format="concise"),
        )
        self.assertTrue(self.urls)
        for url in self.urls:
            _assert_valid_url(self, url)

    def test_rule_list_url_is_valid(self):
        self._run(client.cmd_rule_list, _Args(format="concise"))
        self.assertTrue(self.urls)
        for url in self.urls:
            _assert_valid_url(self, url)

    # --- feature 003: master categories + search folders ---------------------------------------

    def test_category_list_url_is_valid(self):
        self._run(client.cmd_category_list, _Args(format="concise"))
        self.assertTrue(self.urls)
        for url in self.urls:
            _assert_valid_url(self, url)

    def test_category_ensure_get_and_post_urls_are_valid(self):
        # GET (absent → {"value": []}) then POST to masterCategories.
        self._run(client.cmd_category_ensure, _Args(name="Needs attention", color="preset9"))
        self.assertTrue(any("masterCategories" in u for u in self.urls))
        for url in self.urls:
            _assert_valid_url(self, url)

    def test_searchfolder_list_url_is_valid(self):
        self._run(client.cmd_searchfolder_list, _Args(format="concise"))
        self.assertTrue(any("searchfolders/childFolders" in u for u in self.urls))
        for url in self.urls:
            _assert_valid_url(self, url)

    def test_searchfolder_create_url_with_category_filter_is_valid(self):
        # The filterQuery carries spaces and quotes — it lives in the POST body (not the URL), but the
        # POST path itself must be valid; assert no query/path corruption regardless.
        self._run(
            client.cmd_searchfolder_create,
            _Args(name="Needs attention", category="Needs attention", filter_query=None,
                  source_folders=["inbox"], include_nested=True),
        )
        self.assertTrue(any(u.endswith("/me/mailFolders/searchfolders/childFolders") for u in self.urls))
        for url in self.urls:
            _assert_valid_url(self, url)

    def test_searchfolder_remove_url_is_valid(self):
        self._run(client.cmd_searchfolder_remove, _Args(folder_id="AAMk=Sf/Id"))
        self.assertTrue(self.urls)
        for url in self.urls:
            _assert_valid_url(self, url)


if __name__ == "__main__":
    unittest.main()
