from demopilot.models import DemoRequest, build_intent_statement


def test_intent_profile_is_persisted_in_request_and_statement() -> None:
    request = DemoRequest(
        client_name="Sales",
        project_name="Quote",
        industry="B2B",
        scenario="销售希望展示报价计算流程。",
        audience="销售",
        evaluation_case_id="sales-intent-test",
        evaluation_intent_profile="raw-sales",
    )
    statement = build_intent_statement(request)
    assert request.evaluation_intent_profile == "raw-sales"
    assert statement["evaluation"]["intent_profile"] == "raw-sales"
