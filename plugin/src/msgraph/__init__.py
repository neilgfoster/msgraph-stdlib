"""msgraph-stdlib kernel — stdlib only, zero dependencies, no backend.

Reads Outlook mail and authors/verifies native Outlook message rules via Microsoft
Graph. The kernel is plain Python: importable for scripting AND runnable by skills via
`python3 -m msgraph.client ...` / `python3 "${CLAUDE_PLUGIN_ROOT}/src/msgraph/client.py" ...`.

Safety model is structural: read is Mail.Read-only; rule authoring needs a separate
MailboxSettings.ReadWrite consent; rule-create refuses unless the predicate was verified
read-only first; rule actions only file-to-folder, never delete.
"""
