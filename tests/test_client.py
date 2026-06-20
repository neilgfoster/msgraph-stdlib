"""Offline unit tests for the msgraph-stdlib kernel.

The single `_http` seam is the only network boundary (research D8); every test patches it (or the
on-disk state paths) so the suite is stdlib-only and network-free. Written as ``unittest.TestCase``
classes so they run under both ``python3 -m unittest discover -s tests`` (quickstart.md) and
``pytest`` (CI). Covers the catch-set logic, output shaping, the scope ratchet, and the
verify-then-install gate that make the safety model structural.
"""

from __future__ import annotations

import json
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


# Note: the stdlib-only guard (T003) lives in its own template-aligned module, tests/test_stdlib_only.py
# (denylist grep + AST walk over plugin/src), so it is not duplicated here.


# ================================================================================================
# T009 — describe / TOOLS catalog discovery
# ================================================================================================
class DescribeTest(unittest.TestCase):
    EXPECTED = {
        "describe",
        "auth-login",
        "mail-list",
        "mail-get",
        "message-move",
        "rule-list",
        "rule-verify",
        "rule-create",
        "rule-remove",
        "category-list",
        "category-ensure",
        "folder-list",
        "searchfolder-list",
        "searchfolder-create",
        "searchfolder-remove",
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
        read_only = (
            "mail-list",
            "mail-get",
            "rule-list",
            "rule-verify",
            "category-list",
            "searchfolder-list",
        )
        for name in read_only:
            tool = next(t for t in client.TOOLS if t["name"] == name)
            self.assertTrue(tool["annotations"]["readOnlyHint"], f"{name} should be read-only")

    def test_catalog_scopes_match_the_ratchet(self):
        # The TOOLS scope strings are the single source of truth for the verb→scope matrix.
        want = {
            "category-list": "MailboxSettings.Read",
            "category-ensure": "MailboxSettings.ReadWrite",
            "searchfolder-list": "Mail.Read",
            "searchfolder-create": "Mail.ReadWrite",
            "searchfolder-remove": "Mail.ReadWrite",
            "message-move": "Mail.ReadWrite",
        }
        for name, scope in want.items():
            tool = next(t for t in client.TOOLS if t["name"] == name)
            self.assertEqual(tool["scope"], scope, f"{name} scope drift")


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

    def test_renders_non_header_predicates_and_actions(self):
        # Most real rules use predicates other than headerContains; they must be legible, not hidden.
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        rules = {
            "value": [
                {
                    "id": "r2",
                    "displayName": "From boss",
                    "isEnabled": False,
                    "conditions": {
                        "senderContains": ["boss@example.com"],
                        "fromAddresses": [{"emailAddress": {"name": "Boss", "address": "boss@example.com"}}],
                        "sentToMe": True,
                        "importance": "high",
                    },
                    "actions": {"markAsRead": True, "assignCategories": ["Work"]},
                }
            ]
        }
        out = self._render(rules)
        self.assertIn("From boss", out)
        self.assertIn("disabled", out)
        self.assertIn("sender contains: boss@example.com", out)
        self.assertIn("from addresses: boss@example.com", out)
        self.assertIn("sent to me: yes", out)
        self.assertIn("importance: high", out)
        self.assertIn("mark as read: yes", out)
        self.assertIn("assign categories: Work", out)
        # No false "(other criteria)" / "(other action)" placeholder leaks through.
        self.assertNotIn("other criteria", out)

    def test_resolves_deeply_nested_folder_id_to_name(self):
        # rule-list shows the folder NAME, resolved at ANY nesting depth, not the opaque id.
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        rules = {
            "value": [
                {
                    "id": "r3",
                    "displayName": "Filed",
                    "isEnabled": True,
                    "conditions": {"senderContains": ["x@y.com"]},
                    "actions": {"moveToFolder": "grandchild-1", "copyToFolder": "unknown-id"},
                }
            ]
        }
        # Folder tree served across the child-folder endpoints (top → child → grandchild).
        folder_tree = {
            "/me/mailFolders": [{"id": "top-1", "displayName": "Top", "childFolderCount": 1}],
            "/me/mailFolders/top-1/childFolders": [
                {"id": "child-1", "displayName": "Mid", "childFolderCount": 1}
            ],
            "/me/mailFolders/child-1/childFolders": [
                {"id": "grandchild-1", "displayName": "House 2026", "childFolderCount": 0}
            ],
        }
        out = self._render(rules, folder_tree)
        self.assertIn('move to folder: "House 2026"', out)  # depth-3 child resolved
        self.assertNotIn("grandchild-1", out)
        self.assertIn("copy to folder: unknown-id", out)  # unresolved id shown raw, not hidden

    def _render(self, payload, folder_tree=None):
        import contextlib
        import io

        def responder(method, url, **kw):
            if "/messageRules" in url:
                return payload
            if folder_tree:
                for path, value in folder_tree.items():
                    # Match the path portion of the URL, ignoring the query string.
                    if url.split("?", 1)[0].endswith(path):
                        return {"value": value}
            return {"value": []}

        client._http = _HttpRecorder(responder)
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


# ================================================================================================
# T017 — US1: category-assigning rules + category list/ensure
# ================================================================================================
class CategoryTest(StatePathMixin):
    def _capture(self, fn, args):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(fn(args), 0)
        return buf.getvalue()

    def test_category_list_read_scope_and_shaping(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        cats = {"value": [{"id": "c1", "displayName": "Needs attention", "color": "preset9"}]}
        rec = _HttpRecorder(lambda method, url, **kw: cats)
        client._http = rec
        out = self._capture(client.cmd_category_list, _Args(format="concise"))
        self.assertIn("Needs attention", out)
        self.assertIn("preset9", out)
        self.assertEqual(rec.methods(), ["GET"])  # read-only

    def test_category_list_refuses_read_token_missing(self):
        with self.assertRaises(client.SteerError):
            client.cmd_category_list(_Args(format="concise"))

    def test_ensure_creates_when_absent(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")

        def responder(method, url, **kw):
            if method == "GET":
                return {"value": []}
            return {"id": "c-new", "displayName": "Needs attention", "color": "preset9"}

        rec = _HttpRecorder(responder)
        client._http = rec
        self._capture(client.cmd_category_ensure, _Args(name="Needs attention", color="preset9"))
        post = next((c for c in rec.calls if c[0] == "POST"), None)
        self.assertIsNotNone(post, "absent category must be POSTed")
        self.assertEqual(post[1], f"{client.GRAPH}/me/outlook/masterCategories")
        self.assertEqual(post[3], {"displayName": "Needs attention", "color": "preset9"})

    def test_ensure_is_noop_when_present(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")
        cats = {"value": [{"id": "c1", "displayName": "needs ATTENTION", "color": "preset5"}]}
        rec = _HttpRecorder(lambda method, url, **kw: cats)
        client._http = rec
        out = self._capture(client.cmd_category_ensure, _Args(name="Needs attention", color="preset9"))
        self.assertIn("already exists", out)
        self.assertNotIn("POST", rec.methods())  # case-insensitive match → no create

    def test_ensure_refuses_without_write_scope(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        with self.assertRaises(client.SteerError):
            client.cmd_category_ensure(_Args(name="X", color="preset9"))

    def test_rule_create_assign_category_shapes_action_and_ensures(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")
        client.record_verification(["List-Unsubscribe"], 4)

        def responder(method, url, **kw):
            if method == "GET" and "masterCategories" in url:
                return {"value": []}  # category absent → ensure creates it
            if method == "POST" and "masterCategories" in url:
                return {"id": "c-new", "displayName": "Needs attention", "color": "preset9"}
            if method == "POST":  # the rule itself
                return {"id": "rule-new"}
            return {}

        rec = _HttpRecorder(responder)
        client._http = rec
        self._capture(
            client.cmd_rule_create,
            _Args(
                name="Flag",
                header_contains=["List-Unsubscribe"],
                move_to_folder=None,
                assign_category=["Needs attention"],
            ),
        )
        rule_post = next(c for c in rec.calls if c[0] == "POST" and c[1].endswith("/messageRules"))
        actions = rule_post[3]["actions"]
        self.assertEqual(actions["assignCategories"], ["Needs attention"])
        self.assertNotIn("moveToFolder", actions)  # category-only rule
        self.assertNotIn("delete", actions)
        # the category was ensured (a POST to masterCategories happened before the rule POST)
        self.assertTrue(any(c[0] == "POST" and "masterCategories" in c[1] for c in rec.calls))

    def test_rule_create_combined_move_and_category(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")
        client.record_verification(["List-Unsubscribe"], 2)

        def responder(method, url, **kw):
            if "/me/mailFolders?" in url:
                return {"value": [{"id": "f-1", "displayName": "News"}]}
            if "masterCategories" in url:
                return {"value": [{"id": "c1", "displayName": "Needs attention", "color": "preset9"}]}
            if method == "POST":
                return {"id": "rule-new"}
            return {}

        rec = _HttpRecorder(responder)
        client._http = rec
        self._capture(
            client.cmd_rule_create,
            _Args(
                name="Both",
                header_contains=["List-Unsubscribe"],
                move_to_folder="News",
                assign_category=["Needs attention"],
            ),
        )
        rule_post = next(c for c in rec.calls if c[0] == "POST" and c[1].endswith("/messageRules"))
        actions = rule_post[3]["actions"]
        self.assertEqual(actions["moveToFolder"], "f-1")
        self.assertEqual(actions["assignCategories"], ["Needs attention"])

    def test_rule_create_refuses_when_no_action(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")
        client.record_verification(["X"], 1)
        client._http = _HttpRecorder()
        with self.assertRaises(client.SteerError):
            client.cmd_rule_create(
                _Args(name="N", header_contains=["X"], move_to_folder=None, assign_category=None)
            )

    def test_rule_create_category_still_requires_verify(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")  # write scope, no marker
        client._http = _HttpRecorder()
        with self.assertRaises(client.SteerError):
            client.cmd_rule_create(
                _Args(name="N", header_contains=["Unverified"], move_to_folder=None, assign_category=["Lbl"])
            )


# ================================================================================================
# T030 — US2: search-folder create / list / remove + the new scope tier
# ================================================================================================
class SearchFolderTest(StatePathMixin):
    def _capture(self, fn, args):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(fn(args), 0)
        return buf.getvalue()

    def test_filter_query_for_category_escapes_quotes(self):
        self.assertEqual(
            client._filter_query_for_category("Needs attention"),
            "categories/any(c:c eq 'Needs attention')",
        )
        self.assertEqual(
            client._filter_query_for_category("O'Brien"),
            "categories/any(c:c eq 'O''Brien')",
        )

    def test_create_refuses_without_mail_readwrite(self):
        # A read OR rules token lacks Mail.ReadWrite → structural ratchet refusal (FR-008/FR-012).
        for scope in (
            "Mail.Read MailboxSettings.Read offline_access",
            "Mail.Read MailboxSettings.ReadWrite offline_access",
        ):
            self._sign_in(scope)
            with self.assertRaises(client.SteerError):
                client.cmd_searchfolder_create(
                    _Args(
                        name="N",
                        category="Needs attention",
                        filter_query=None,
                        source_folders=None,
                        include_nested=True,
                    )
                )

    def test_create_refuses_without_filter(self):
        self._sign_in("Mail.ReadWrite MailboxSettings.Read offline_access")
        client._http = _HttpRecorder()
        with self.assertRaises(client.SteerError):
            client.cmd_searchfolder_create(
                _Args(name="N", category=None, filter_query=None, source_folders=None, include_nested=True)
            )

    def test_create_shapes_body_with_odata_type(self):
        self._sign_in("Mail.ReadWrite MailboxSettings.Read offline_access")
        rec = _HttpRecorder(lambda method, url, **kw: {"id": "sf-new"})
        client._http = rec
        self._capture(
            client.cmd_searchfolder_create,
            _Args(
                name="Needs attention",
                category="Needs attention",
                filter_query=None,
                source_folders=["inbox"],
                include_nested=True,
            ),
        )
        post = next(c for c in rec.calls if c[0] == "POST")
        self.assertTrue(post[1].endswith("/me/mailFolders/searchfolders/childFolders"))
        body = post[3]
        self.assertEqual(body["@odata.type"], "microsoft.graph.mailSearchFolder")
        self.assertEqual(body["includeNestedFolders"], True)
        self.assertEqual(body["sourceFolderIds"], ["inbox"])  # well-known name passed through
        self.assertEqual(body["filterQuery"], "categories/any(c:c eq 'Needs attention')")

    def test_create_explicit_filter_overrides_category(self):
        self._sign_in("Mail.ReadWrite MailboxSettings.Read offline_access")
        rec = _HttpRecorder(lambda method, url, **kw: {"id": "sf"})
        client._http = rec
        self._capture(
            client.cmd_searchfolder_create,
            _Args(
                name="Big",
                category="Ignored",
                filter_query="hasAttachments eq true",
                source_folders=None,
                include_nested=False,
            ),
        )
        body = next(c for c in rec.calls if c[0] == "POST")[3]
        self.assertEqual(body["filterQuery"], "hasAttachments eq true")
        self.assertEqual(body["includeNestedFolders"], False)
        self.assertEqual(body["sourceFolderIds"], ["inbox"])  # default

    def test_list_read_scope_only(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        payload = {
            "value": [
                {
                    "id": "sf1",
                    "displayName": "Needs attention",
                    "filterQuery": "categories/any(c:c eq 'Needs attention')",
                    "includeNestedFolders": True,
                    "sourceFolderIds": ["inbox"],
                }
            ]
        }
        rec = _HttpRecorder(lambda method, url, **kw: payload)
        client._http = rec
        out = self._capture(client.cmd_searchfolder_list, _Args(format="concise"))
        self.assertIn("Needs attention", out)
        self.assertIn("sf1", out)
        self.assertEqual(rec.methods(), ["GET"])

    def test_remove_issues_one_delete_on_the_folder_not_mail(self):
        self._sign_in("Mail.ReadWrite MailboxSettings.Read offline_access")
        rec = _HttpRecorder()
        client._http = rec
        self._capture(client.cmd_searchfolder_remove, _Args(folder_id="sf1"))
        self.assertEqual(rec.methods(), ["DELETE"])
        url = rec.calls[0][1]
        self.assertTrue(url.endswith("/me/mailFolders/sf1"))
        self.assertNotIn("/me/messages", url)  # never a message-level delete

    def test_remove_refuses_without_mail_readwrite(self):
        self._sign_in("Mail.Read MailboxSettings.ReadWrite offline_access")  # rules tier, not folders
        with self.assertRaises(client.SteerError):
            client.cmd_searchfolder_remove(_Args(folder_id="sf1"))


# ================================================================================================
# message-move — per-message MOVE verb (the new Mail.ReadWrite message-write tier). MOVE only.
# ================================================================================================
class MessageMoveTest(StatePathMixin):
    def _capture(self, fn, args, expect=0):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(fn(args), expect)
        return buf.getvalue()

    def test_refuses_without_mail_readwrite(self):
        # read AND rules tiers both lack Mail.ReadWrite → structural ratchet refusal.
        for scope in (
            "Mail.Read MailboxSettings.Read offline_access",
            "Mail.Read MailboxSettings.ReadWrite offline_access",
        ):
            self._sign_in(scope)
            with self.assertRaises(client.SteerError):
                client.cmd_message_move(
                    _Args(message_ids=["m1"], destination_folder="archive", dry_run=False, format="concise")
                )

    def test_dry_run_writes_nothing_and_lists_set(self):
        self._sign_in("Mail.ReadWrite MailboxSettings.Read offline_access")
        msg = {"id": "m1", "subject": "Hello", "from": {"emailAddress": {"address": "a@b.c"}}}
        rec = _HttpRecorder(lambda method, url, **kw: msg)
        client._http = rec
        out = self._capture(
            client.cmd_message_move,
            _Args(message_ids=["m1"], destination_folder="archive", dry_run=True, format="concise"),
        )
        self.assertIn("DRY RUN", out)
        self.assertIn("Hello", out)
        self.assertNotIn("POST", rec.methods())  # nothing written
        self.assertNotIn("DELETE", rec.methods())  # never a delete

    def test_move_posts_move_op_never_delete(self):
        self._sign_in("Mail.ReadWrite MailboxSettings.Read offline_access")
        rec = _HttpRecorder(lambda method, url, **kw: {"id": "new-m1"})
        client._http = rec
        out = self._capture(
            client.cmd_message_move,
            _Args(message_ids=["m1"], destination_folder="archive", dry_run=False, format="concise"),
        )
        self.assertEqual(rec.methods(), ["POST"])
        post = rec.calls[0]
        self.assertTrue(post[1].endswith("/me/messages/m1/move"))
        self.assertEqual(post[3], {"destinationId": "archive"})  # well-known name verbatim
        self.assertNotIn("DELETE", rec.methods())
        self.assertIn("new-m1", out)
        self.assertIn("Reversible", out)

    def test_batch_safe_partial_failure_reports_per_message(self):
        self._sign_in("Mail.ReadWrite MailboxSettings.Read offline_access")

        def responder(method, url, **kw):
            if url.endswith("/me/messages/bad/move"):
                raise client.SteerError("Graph request failed (404)")
            return {"id": "new"}

        client._http = _HttpRecorder(responder)
        out = self._capture(
            client.cmd_message_move,
            _Args(message_ids=["ok", "bad"], destination_folder="archive", dry_run=False, format="concise"),
            expect=0,  # at least one succeeded → exit 0
        )
        self.assertIn("Moved 1/2", out)
        self.assertIn("✓ ok", out)
        self.assertIn("✗ bad", out)


class FolderListTest(StatePathMixin):
    def _capture(self, fn, args):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(fn(args), 0)
        return buf.getvalue()

    def _tree_responder(self):
        """Two-level tree: Inbox (1 child) + Archive + the virtual Search Folders node."""
        top = {
            "value": [
                {
                    "id": "inbox",
                    "displayName": "Inbox",
                    "parentFolderId": "root",
                    "totalItemCount": 1280,
                    "unreadItemCount": 37,
                    "childFolderCount": 1,
                },
                {
                    "id": "archive",
                    "displayName": "Archive",
                    "parentFolderId": "root",
                    "totalItemCount": 8901,
                    "unreadItemCount": 0,
                    "childFolderCount": 0,
                },
                {
                    "id": "sfroot",
                    "displayName": "Search Folders",
                    "parentFolderId": "root",
                    "totalItemCount": 0,
                    "unreadItemCount": 0,
                    "childFolderCount": 0,
                },
            ]
        }
        children = {
            "value": [
                {
                    "id": "receipts",
                    "displayName": "Receipts",
                    "parentFolderId": "inbox",
                    "totalItemCount": 412,
                    "unreadItemCount": 0,
                    "childFolderCount": 0,
                }
            ]
        }

        def responder(method, url, **kw):
            return children if "childFolders" in url else top

        return responder

    def test_concise_renders_nested_tree_with_counts(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        rec = _HttpRecorder(self._tree_responder())
        client._http = rec
        out = self._capture(client.cmd_folder_list, _Args(format="concise", include_hidden=False))
        self.assertIn('"Inbox"', out)
        self.assertIn("1280 total, 37 unread", out)
        self.assertIn('  - "Receipts"', out)  # nested indentation
        self.assertEqual(rec.methods(), ["GET", "GET"])  # top + inbox children only

    def test_excludes_virtual_search_folders_node(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        client._http = _HttpRecorder(self._tree_responder())
        out = self._capture(client.cmd_folder_list, _Args(format="concise", include_hidden=False))
        self.assertNotIn("Search Folders", out)
        # Inbox, Archive, Receipts — three real folders, search-folder node dropped.
        self.assertIn("3 mail folder(s)", out)

    def test_detailed_emits_ids_and_parent(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        client._http = _HttpRecorder(self._tree_responder())
        out = self._capture(client.cmd_folder_list, _Args(format="detailed", include_hidden=False))
        data = json.loads(out)
        self.assertEqual(data[0]["id"], "inbox")
        self.assertEqual(data[0]["parentFolderId"], "root")
        self.assertEqual(data[0]["children"][0]["displayName"], "Receipts")

    def test_read_scope_only(self):
        self._sign_in("Mail.Read MailboxSettings.Read offline_access")
        rec = _HttpRecorder(self._tree_responder())
        client._http = rec
        self._capture(client.cmd_folder_list, _Args(format="concise", include_hidden=False))
        self.assertEqual(set(rec.methods()), {"GET"})  # never a write


if __name__ == "__main__":
    unittest.main()
