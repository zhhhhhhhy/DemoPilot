from demopilot.models import DemoRequest, build_intent_statement


def test_intent_statement_preserves_user_dimensions_and_explicit_defaults():
    request = DemoRequest(
        client_name="远山科技",
        project_name="运营指挥台",
        industry="企业服务",
        scenario="运营团队需要识别异常并追踪处理结果。",
        audience="运营负责人",
        must_haves=["异常筛选", "状态追踪"],
        boundaries=["只做浏览器内演示"],
        priority="先完成异常闭环",
        acceptance_criteria=["点击筛选后能看到异常结果"],
        constraints=["不能连接生产系统"],
        intent_confirmed=True,
    )

    statement = build_intent_statement(request)

    assert statement["status"] == "confirmed"
    assert statement["boundary"] == ["只做浏览器内演示"]
    assert statement["priority"] == "先完成异常闭环"
    assert statement["acceptance"] == ["点击筛选后能看到异常结果"]
    assert statement["constraints"] == ["不能连接生产系统"]
    assert statement["must_haves"] == ["异常筛选", "状态追踪"]


def test_intent_statement_does_not_drop_empty_optional_dimensions():
    request = DemoRequest(
        client_name="远山科技",
        project_name="运营指挥台",
        industry="企业服务",
        scenario="运营团队需要识别异常并追踪处理结果。",
        audience="运营负责人",
    )

    statement = build_intent_statement(request)

    assert statement["boundary"]
    assert statement["acceptance"]
    assert statement["constraints"]
