"""Offline unit tests for the msgraph-stdlib kernel.

The single `_http` seam is the only network boundary (research D8); every test patches it (or the
on-disk state paths) so the suite is stdlib-only and network-free. Written as ``unittest.TestCase``
classes so they run under both ``python3 -m unittest discover -s tests`` (quickstart.md) and
``pytest`` (CI). Covers the catch-set logic, output shaping, the scope ratchet, and the
verify-then-install gate that make the safety model structural.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

# The kernel ships under plugin/src; make it importable without installing the package.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "plugin" / "src"))

import msgraph.client as client  # noqa: E402


class _Args:
    """Tiny stand-in for the argparse namespace the cmd_* handlers expect."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _HttpRecorder:
    """Drop-in replacement for client._http that records calls and returns canned payloads.

    Lets a test assert *which* HTTP verbs/endpoints a command reaches — the structural check that a
    read-only verb never touches a write endpoint and rule-remove issues exactly one DELETE.
    """

    def __init__(self, responder=None):
        self.calls = []  # list of (method, url, token, body)
        self._responder = responder or (lambda method, url, **kw: {})

    def __call__(self, method, url, token=None, body=None, form=False):
        self.calls.append((method, url, token, body))
        return self._responder(method, url, token=token, body=body, form=form)

    def methods(self):
        return [m for m, *_ in self.calls]


class StatePathMixin(unittest.TestCase):
    """Redirect the token cache + verification marker to a throwaway temp dir for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = (client.STATE_DIR, client.TOKEN_PATH, client.MARKER_PATH, client._http)
        client.STATE_DIR = tmp
        client.TOKEN_PATH = tmp / "token.json"
        client.MARKER_PATH = tmp / "verifications.json"

    def tearDown(self):
        client.STATE_DIR, client.TOKEN_PATH, client.MARKER_PATH, client._http = self._orig
        self._tmp.cleanup()

    def _sign_in(self, scope):
        """Seed a non-expired cached token carrying the given scopes."""
        client.save_token(
            {
                "access_token": "fake-access",
                "refresh_token": "fake-refresh",
                "scope": scope,
                "expires_at": 2_000_000_000,  # far future → no refresh
                "account": "user@example.com",
            }
        )


# ================================================================================================
# T003 — zero third-party dependency guard
# ================================================================================================
class ZeroDependencyTest(unittest.TestCase):
    def test_no_third_party_imports_in_source(self):
        banned = re.compile(r"^\s*(?:import|from)\s+(msal|azure|requests)\b", re.MULTILINE)
        for path in (REPO_ROOT / "plugin" / "src").rglob("*.py"):
            self.assertIsNone(
                banned.search(path.read_text(encoding="utf-8")),
                f"{path} imports a forbidden third-party package",
            )


# ================================================================================================
# T009 — describe / TOOLS catalog discovery
# ================================================================================================
class DescribeTest(unittest.TestCase):
    EXPECTED = {
        "describe",
        "auth-login",
        "mail-list",
        "mail-get",
        "rule-list",
        "rule-verify",
        "rule-create",
        "rule-remove",
    }

    def test_catalog_lists_every_verb_with_required_fields(self):
        names = {t["name"] for t in client.TOOLS}
        self.assertEqual(names, self.EXPECTED)
        for tool in client.TOOLS:
            self.assertTrue(tool["description"], f"{tool['name']} missing description")
            self.assertIn("type", tool["inputSchema"])
            for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                self.assertIn(hint, tool["annotations"], f"{tool['name']} missing {hint}")

    def test_describe_one_verb(self):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(client.cmd_describe(_Args(name="rule-verify")), 0)

    def test_describe_unknown_verb_steers(self):
        with self.assertRaises(client.SteerError):
            client.cmd_describe(_Args(name="does-not-exist"))

    def test_read_only_verbs_advertise_read_only(self):
        for name in ("mail-list", "mail-get", "rule-list", "rule-verify"):
            tool = next(t for t in client.TOOLS if t["name"] == name)
            self.assertTrue(tool["annotations"]["readOnlyHint"], f"{name} should be read-only")


# ================================================================================================
# T010 — token cache + scope ratchet
# ================================================================================================
class TokenCacheTest(StatePathMixin):
    def test_round_trip_and_permissions(self):
        client.save_token({"access_token": "x", "scope": "Mail.Read", "expires_at": 0})
        self.assertEqual(client.load_token()["access_token"], "x")
        mode = client.TOKEN_PATH.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, "token cache must be written 0600")

    def test_require_scopes_rejects_read_only_for_write(self):
        read_tok = {"scope": "Mail.Read MailboxSettings.Read"}
        with self.assertRaises(client.SteerError):
            client._require_scopes(read_tok, client.WRITE_SCOPE)
        # ...but accepts a token that holds the scope.
        write_tok = {"scope": "Mail.Read MailboxSettings.ReadWrite"}
        client._require_scopes(write_tok, client.WRITE_SCOPE)  # no raise

    def test_require_scopes_not_signed_in(self):
        with self.assertRaises(client.SteerError):
            client._require_scopes({}, "Mail.Read")


# ================================================================================================
# T016 — mail-list / mail-get
# ================================================================================================
class MailReadTest(StatePathMixin):
    def test_mail_list_shaping_and_limit(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        payload = {
            "value": [
                {
                    "id": "m1",
                    "subject": "Hello",
                    "from": {"emailAddress": {"address": "a@x.com"}},
                    "receivedDateTime": "2026-06-01T00:00:00Z",
                }
            ]
        }
        rec = _HttpRecorder(lambda method, url, **kw: payload)
        client._http = rec
        out = self._capture(client.cmd_mail_list, _Args(limit=10, format="concise"))
        self.assertIn("Hello", out)
        self.assertIn("a@x.com", out)
        # only a read (GET) endpoint is reached
        self.assertEqual(rec.methods(), ["GET"])
        self.assertIn("$top=10", rec.calls[0][1])

    def test_mail_get_surfaces_headers(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        msg = {
            "id": "m1",
            "subject": "Newsletter",
            "from": {"emailAddress": {"address": "news@x.com"}},
            "receivedDateTime": "2026-06-01T00:00:00Z",
            "internetMessageHeaders": [{"name": "List-Unsubscribe", "value": "<mailto:x>"}],
        }
        client._http = _HttpRecorder(lambda method, url, **kw: msg)
        out = self._capture(client.cmd_mail_get, _Args(message_id="m1", format="concise"))
        self.assertIn("List-Unsubscribe", out)

    def test_not_signed_in_steers(self):
        # no token saved
        with self.assertRaises(client.SteerError):
            client.cmd_mail_list(_Args(limit=5, format="concise"))

    def _capture(self, fn, args):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(fn(args), 0)
        return buf.getvalue()


# ================================================================================================
# T021 — catch-set + verify (the safety keystone)
# ================================================================================================
class CatchSetTest(StatePathMixin):
    MESSAGES = [
        {
            "id": "m1",
            "subject": "Weekly news",
            "from": {"emailAddress": {"address": "news@x.com"}},
            "internetMessageHeaders": [{"name": "List-Unsubscribe", "value": "<mailto:u>"}],
        },
        {
            "id": "m2",
            "subject": "Personal",
            "from": {"emailAddress": {"address": "friend@x.com"}},
            "internetMessageHeaders": [{"name": "From", "value": "friend@x.com"}],
        },
    ]

    def test_compute_catch_set_match(self):
        matched = client.compute_catch_set(self.MESSAGES, ["List-Unsubscribe"])
        self.assertEqual([m["id"] for m in matched], ["m1"])

    def test_compute_catch_set_requires_all_substrings(self):
        self.assertEqual(client.compute_catch_set(self.MESSAGES, ["List-Unsubscribe", "nope"]), [])

    def test_compute_catch_set_empty_on_no_match(self):
        self.assertEqual(client.compute_catch_set(self.MESSAGES, ["absent-header"]), [])

    def test_verify_records_marker_and_only_reads(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        import contextlib
        import io

        rec = _HttpRecorder(lambda method, url, **kw: {"value": self.MESSAGES})
        client._http = rec
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                client.cmd_rule_verify(_Args(header_contains=["List-Unsubscribe"], format="concise")), 0
            )
        # a marker now exists for this predicate set
        self.assertTrue(client.read_verification(["List-Unsubscribe"]))
        # verify performs no writes — only GETs against Graph
        self.assertEqual(set(rec.methods()), {"GET"})


# ================================================================================================
# T024 — rule-list
# ================================================================================================
class RuleListTest(StatePathMixin):
    def test_shaping_and_empty_state(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        rules = {
            "value": [
                {
                    "id": "r1",
                    "displayName": "Newsletters",
                    "isEnabled": True,
                    "conditions": {"headerContains": ["List-Unsubscribe"]},
                    "actions": {"moveToFolder": "folder-123"},
                }
            ]
        }
        out = self._render(rules)
        self.assertIn("Newsletters", out)
        self.assertIn("List-Unsubscribe", out)
        empty = self._render({"value": []})
        self.assertIn("No inbox message rules", empty)

    def _render(self, payload):
        import contextlib
        import io

        client._http = _HttpRecorder(lambda method, url, **kw: payload)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(client.cmd_rule_list(_Args(format="concise")), 0)
        return buf.getvalue()


# ================================================================================================
# T029 — rule-create gate (scope + verify-then-install)
# ================================================================================================
class RuleCreateTest(StatePathMixin):
    def test_refuses_without_write_scope(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")  # read-only
        with self.assertRaises(client.SteerError):
            client.cmd_rule_create(_Args(name="N", header_contains=["X"], move_to_folder="F"))

    def test_refuses_without_prior_verify(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")  # write scope, but no marker
        client._http = _HttpRecorder()
        with self.assertRaises(client.SteerError):
            client.cmd_rule_create(_Args(name="N", header_contains=["Never-Verified"], move_to_folder="F"))

    def test_success_builds_move_to_folder_and_never_delete(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")
        client.record_verification(["List-Unsubscribe"], 3)

        def responder(method, url, **kw):
            if url.endswith("/me/mailFolders?$top=100&$select=id,displayName"):
                return {"value": [{"id": "folder-123", "displayName": "Newsletters"}]}
            if method == "POST":
                return {"id": "rule-new"}
            return {}

        import contextlib
        import io

        rec = _HttpRecorder(responder)
        client._http = rec
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                client.cmd_rule_create(
                    _Args(
                        name="Newsletters",
                        header_contains=["List-Unsubscribe"],
                        move_to_folder="Newsletters",
                    )
                ),
                0,
            )
        post = next(c for c in rec.calls if c[0] == "POST")
        body = post[3]
        self.assertIn("moveToFolder", body["actions"])
        self.assertNotIn("delete", body["actions"])
        self.assertEqual(body["actions"]["moveToFolder"], "folder-123")
        # no DELETE on any message endpoint
        self.assertNotIn("DELETE", rec.methods())


# ================================================================================================
# T032 — rule-remove (reversibility primitive)
# ================================================================================================
class RuleRemoveTest(StatePathMixin):
    def test_issues_exactly_one_delete_on_the_rule(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")
        rec = _HttpRecorder()
        client._http = rec
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(client.cmd_rule_remove(_Args(rule_id="r1")), 0)
        self.assertEqual(rec.methods(), ["DELETE"])
        method, url, *_ = rec.calls[0]
        self.assertTrue(url.endswith("/me/mailFolders/inbox/messageRules/r1"))
        # never a message-level call
        self.assertNotIn("/me/messages", url)


if __name__ == "__main__":
    unittest.main()
