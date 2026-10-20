"""Narrow regressions for observable restoration and rejection boundaries."""

import asyncio

import pytest
from demopilot.quotation_browser import (
    _active_fields,
    _assert_rejection_message,
    _form_mismatches,
)


def test_committed_field_comparison_catches_stale_fields_without_numeric_false_alarm():
    expected = dict(product="B", quantity="3", second_quantity="0", manual_rate="80")
    actual = dict(product="A", quantity="10", second_quantity="0.0", manual_rate="80.00")
    assert _form_mismatches(expected, actual) == {
        "product": dict(expected="B", actual="A"),
        "quantity": dict(expected="3", actual="10"),
    }
    assert _form_mismatches({"manual_rate": ""}, {"manual_rate": ""}) == {}
    assert _form_mismatches({"quantity": "1"}, {"quantity": None})


def test_optional_fields_follow_business_capabilities():
    assert "manual_rate" not in _active_fields(dict(version=1, workflow="single_manager"))
    assert "shipping" not in _active_fields(dict(version=1, workflow="manual_override"))
    fields = _active_fields(dict(version=2, workflow="manual_override"))
    assert fields["shipping"] == "shipping" and fields["manual_rate"] == "manual-rate"


class ErrorLocator:
    def __init__(self, visible, text):
        self.visible, self.text = visible, text

    async def is_visible(self):
        return self.visible

    async def inner_text(self):
        return self.text


class ErrorPage:
    def __init__(self, visible=True, text="Reason shown to seller"):
        self.error = ErrorLocator(visible, text)

    def locator(self, selector):
        assert selector == "#error"
        return self.error


@pytest.mark.parametrize("visible,text", [(False, "Reason"), (True, "  ")])
def test_clickable_rejection_requires_visible_nonempty_reason(visible, text):
    with pytest.raises(AssertionError, match="visible nonempty #error"):
        asyncio.run(_assert_rejection_message(
            ErrorPage(visible, text), accepted=False, action="accept", button_disabled=False,
        ))


def test_disabled_action_and_non_actions_need_no_error_message():
    # No page is provided: these exceptions must not require any error element.
    for accepted, action, disabled in [
        (False, "approve", True), (False, "reload", None),
        (False, None, None), (True, "calculate", False),
    ]:
        result = asyncio.run(_assert_rejection_message(
            None, accepted=accepted, action=action, button_disabled=disabled,
        ))
        assert result["required"] is False


def test_clickable_rejection_records_actual_reason():
    result = asyncio.run(_assert_rejection_message(
        ErrorPage(text="  Only the owner may accept.  "),
        accepted=False, action="accept", button_disabled=False,
    ))
    assert result == dict(
        required=True, button_disabled=False, visible=True, text="Only the owner may accept.",
    )
