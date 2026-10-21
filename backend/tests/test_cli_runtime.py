"""Runtime controls with synthetic transport signals; never model accuracy."""
import asyncio
import os

import pytest

from demopilot.cli_runtime import CliRuntimeGuard, connection_environment, transport_failure


async def reachable():
    return dict(passed=True, model_calls=0)


def test_two_failures_pause_all_waiters_then_only_one_real_call_can_recover():
    async def scenario():
        probes=[]
        async def probe():
            probes.append(True)
            return dict(passed=True, model_calls=0)
        guard=CliRuntimeGuard(probe=probe)
        first=await guard.before_call()
        assert first.half_open and guard.state=='half_open'
        await guard.after_call(first)
        a,b=await guard.before_call(),await guard.before_call()
        await guard.after_call(a,RuntimeError('workspace routing discovery failed'))
        assert guard.state=='ready'
        await guard.after_call(b,RuntimeError('workspace routing discovery failed'))
        assert guard.state=='manual_pause' and guard.failures==2
        waiting=asyncio.create_task(guard.before_call())
        await asyncio.sleep(.01)
        assert not waiting.done() and len(probes)==1
        await guard.recheck()
        lease=await asyncio.wait_for(waiting,.5)
        second=asyncio.create_task(guard.before_call())
        await asyncio.sleep(.01)
        assert not second.done()  # HTTPS alone cannot release the queue.
        await guard.after_call(lease)
        normal=await asyncio.wait_for(second,.5)
        assert not normal.half_open and guard.state=='ready' and len(probes)==2
    asyncio.run(scenario())


def test_stale_inflight_success_cannot_clear_outage_and_failed_half_open_stays_paused():
    async def scenario():
        guard=CliRuntimeGuard(probe=reachable)
        await guard.after_call(await guard.before_call())
        a,b,old=await guard.before_call(),await guard.before_call(),await guard.before_call()
        await guard.after_call(a,RuntimeError('tls handshake eof'))
        await guard.after_call(b,RuntimeError('workspace routing discovery failed'))
        await guard.after_call(old)
        assert guard.state=='manual_pause'
        await guard.recheck()
        await guard.after_call(await guard.before_call(),RuntimeError('workspace routing discovery failed'))
        assert guard.state=='manual_pause'
        waiter=asyncio.create_task(guard.before_call())
        await asyncio.sleep(.01)
        assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    asyncio.run(scenario())


def test_resume_gap_checks_before_any_new_call_and_never_automatically_replays():
    async def scenario():
        checks=[]
        async def probe():
            checks.append(True)
            return dict(passed=True)
        guard=CliRuntimeGuard(probe=probe)
        lease=await guard.before_call()
        await guard.after_call(lease)
        old=await guard.before_call()
        await guard.observe_gap(150)
        assert guard.state=='paused'
        await guard.after_call(old)
        assert guard.state=='paused'
        recovery=await guard.before_call()
        assert recovery.half_open and len(checks)==2
        assert guard.state=='half_open'
        await guard.after_call(recovery)
        assert guard.state=='ready'
    asyncio.run(scenario())


def test_failed_connection_check_pauses_without_busy_retry_or_model_start():
    async def scenario():
        calls=[]
        async def probe():
            calls.append(True)
            return dict(passed=False)
        guard=CliRuntimeGuard(probe=probe)
        waiter=asyncio.create_task(guard.before_call())
        await asyncio.sleep(.03)
        assert guard.state=='manual_pause' and len(calls)==1 and not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert len(calls)==1
    asyncio.run(scenario())


def test_new_host_gap_does_not_bypass_explicit_manual_pause():
    async def scenario():
        guard=CliRuntimeGuard(probe=reachable)
        first=await guard.before_call()
        await guard.after_call(first,RuntimeError('workspace routing discovery failed'))
        assert guard.state=='manual_pause'
        await guard.observe_gap(200)
        assert guard.state=='manual_pause'
    asyncio.run(scenario())


def test_business_failures_are_not_connection_failures():
    assert not transport_failure(RuntimeError('wrong total or missing quantity field'))
    assert not transport_failure(RuntimeError('Codex CLI Core Builder timed out'))
    assert transport_failure(RuntimeError('workspace routing discovery failed'))


@pytest.mark.parametrize('working', [True,False,None])
def test_child_proxy_repair_preserves_global_environment_and_working_custom_proxy(monkeypatch,working):
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:10001')
    monkeypatch.setattr('demopilot.cli_runtime._local_proxy_available',lambda url:working if '10001' in url else True)
    monkeypatch.setattr('demopilot.cli_runtime._windows_proxy',lambda:'http://127.0.0.1:10002')
    env=connection_environment()
    assert os.environ['HTTPS_PROXY']=='http://127.0.0.1:10001'
    assert env['HTTPS_PROXY']==('http://127.0.0.1:10002' if working is False else 'http://127.0.0.1:10001')


def test_runtime_api_recheck_never_replays_create_answer_confirm_or_core(tmp_path):
    from fastapi.testclient import TestClient

    from demopilot.config import Settings
    from demopilot.main import create_app
    from demopilot.sales_core import SalesCoreManager
    async def forbidden(*_a,**_kw):
        raise AssertionError('No model may start during connection check')
    settings=Settings(data_dir=tmp_path)
    manager=SalesCoreManager(settings,interviewer=forbidden)
    manager.runtime=CliRuntimeGuard(probe=reachable)
    with TestClient(create_app(settings,sales_core=manager)) as client:
        state=client.post('/api/sales-core/runtime/check').json()
        assert state['state']=='half_open'
        assert client.get('/api/sales-core/sessions').json()==[]
        assert not manager.tasks


def test_resume_detector_terminates_actual_process_and_preserves_partial_trace(tmp_path):
    import sys

    from demopilot.cli_runtime import HostResumeInterrupted
    from demopilot.providers.codex_cli import CodexCliAgentProvider
    async def scenario():
        process=await asyncio.create_subprocess_exec(sys.executable,'-u','-c',
            "import time;print('started',flush=True);time.sleep(60)",
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        guard=CliRuntimeGuard(probe=reachable,resume_gap_seconds=.01)
        provider=CodexCliAgentProvider(timeout_seconds=15,runtime_guard=guard)
        with pytest.raises(HostResumeInterrupted):
            await provider._communicate_workspace_process(process,b'',lambda _e:None,tmp_path/'stdout.jsonl',tmp_path/'stderr.log')
        assert process.returncode is not None and guard.state=='paused'
        assert 'started' in (tmp_path/'stdout.jsonl').read_text()
    asyncio.run(asyncio.wait_for(scenario(),12))


def test_lean_config_keeps_existing_windows_sandbox_without_expanding_workspace(tmp_path,monkeypatch):
    from demopilot.quotation_cli import IsolatedCodexProvider
    if os.name!='nt':
        pytest.skip('Native Windows configuration control')
    (tmp_path/'config.toml').write_text('sandbox_mode="danger-full-access"\n[windows]\nsandbox="elevated"\n')
    monkeypatch.setenv('CODEX_HOME',str(tmp_path))
    args=IsolatedCodexProvider()._command_args('codex.exe',['exec','--sandbox','workspace-write','-'])
    assert 'windows.sandbox=elevated' in args
    assert args[args.index('--sandbox')+1]=='workspace-write'
    assert '--dangerously-bypass-approvals-and-sandbox' not in args
    assert 'sandbox_mode=danger-full-access' not in args
