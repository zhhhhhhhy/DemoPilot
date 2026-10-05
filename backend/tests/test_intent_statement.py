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


def test_agent_core_evaluation_contract_is_persisted_and_explicit():
    request = DemoRequest(
        client_name="评测客户",
        project_name="发票文字识别台",
        industry="财务共享",
        scenario="财务助理需要查看公开合成发票的识别结果。",
        audience="财务助理",
        must_haves=["发票样例列表", "识别结果卡片"],
        provider="codex_cli",
        evaluation_case_id="simple-invoice-ocr-01",
        evaluation_difficulty="simple",
        evaluation_intent="把公开发票图片转成文字识别演示入口。",
        evaluation_goal="选中发票后看到关键字段。",
        evaluation_flow_steps=["收集发票并识别文字"],
        evaluation_method=["点击样例并检查识别结果变化"],
        evaluation_assets=["D:/worker/DemoPilot/evaluation_sets/codex-cli-v1/assets/invoices/invoice-01.jpg"],
    )

    statement = build_intent_statement(request)

    assert statement["evaluation"]["case_id"] == "simple-invoice-ocr-01"
    assert statement["evaluation"]["goal"] == "选中发票后看到关键字段。"
    assert statement["evaluation"]["method"] == ["点击样例并检查识别结果变化"]
    assert statement["evaluation"]["assets"]
