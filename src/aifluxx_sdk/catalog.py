"""Built-in allow-lists used by the offline validator.

The host is the source of truth once GET /api/dev/tools lands. Until then the
CLI uses this copy so validate works in any IDE without a network call.
"""

READ_TOOLS = frozenset(
    {
        "list_compliance_obligations",
        "get_compliance_status",
        "search_documents",
        "get_document",
        "ask_truest",
        "list_mandate_tasks",
        "list_contacts",
        "list_businesses",
    }
)

WRITE_TOOLS = frozenset(
    {
        "send",
        "send_mail",
        "mail_send",
        "create_task",
        "update_task",
        "add_note",
        "create_document",
        "write_document",
    }
)

CONNECTORS = frozenset(
    {
        "gmail_mail",
        "imap_mail",
        "ms_graph_mail",
        "sharepoint",
        "google_drive",
        "onedrive",
        "slack",
    }
)

CATEGORIES = frozenset(
    {
        "finance",
        "compliance",
        "sales",
        "operations",
        "hr",
        "engineering",
        "general",
    }
)

SCHEMAS = frozenset({"truest/agent/v1", "aifluxx/agent/v1"})
