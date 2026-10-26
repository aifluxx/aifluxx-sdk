from aifluxx_sdk.catalog import READ_TOOLS, parse_tool_catalogue
from aifluxx_sdk.templates import TEMPLATES


def test_default_templates_use_the_bundled_allow_list():
    assert "list_compliance_obligations" not in READ_TOOLS
    assert "get_compliance_status" not in READ_TOOLS
    for template in TEMPLATES.values():
        assert set(template.tools) <= READ_TOOLS


def test_parse_tool_catalogue_shapes():
    assert parse_tool_catalogue(["search_documents", "get_document"]) == {"search_documents", "get_document"}
    assert parse_tool_catalogue(
        {"tools": [{"name": "search_documents", "kind": "read", "schema": {"type": "object"}}, {"id": "get_document"}]}
    ) == {"search_documents", "get_document"}
    assert parse_tool_catalogue({"read": ["search_documents"], "write": ["send_mail"]}) == {
        "search_documents",
        "send_mail",
    }
    assert parse_tool_catalogue({"search_documents": {"type": "object"}, "get_document": {"type": "object"}}) == {
        "search_documents",
        "get_document",
    }
    assert parse_tool_catalogue(
        [{"name": "search_documents", "input_schema": {"type": "object"}, "parameters": {"type": "object"}}]
    ) == {"search_documents"}
    assert parse_tool_catalogue({"detail": "Not Found"}) == frozenset()
    assert parse_tool_catalogue({"tools": []}) == frozenset()
