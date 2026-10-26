from aifluxx_sdk.catalog import READ_TOOLS, parse_tool_catalogue
from aifluxx_sdk.templates import DEFAULT_TEMPLATE, TEMPLATES, get_template


def test_default_templates_use_the_bundled_allow_list():
    assert "list_compliance_obligations" not in READ_TOOLS
    assert "get_compliance_status" not in READ_TOOLS
    assert "search_company_knowledge" in READ_TOOLS
    assert "search_documents" not in READ_TOOLS
    for template in TEMPLATES.values():
        assert "search_company_knowledge" in template.tools
        assert "search_documents" not in template.tools
        assert set(template.tools) <= READ_TOOLS


def test_compliance_checklist_alias_is_the_default_template():
    assert get_template("compliance-checklist") is get_template(DEFAULT_TEMPLATE)
    assert DEFAULT_TEMPLATE == "compliance"


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
