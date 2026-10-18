"""Temporary Windows idle-sleep request around a command; no power-plan edits.

Explicit lid/power-button suspension remains possible and is respected. Large
heartbeat gaps are recorded as execution anomalies, not model business errors.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

CONTINUOUS = 0x80000000
SYSTEM_REQUIRED = 0x00000001


def now():
    return datetime.now(UTC)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def run(command, record):
    if record.exists():
        raise RuntimeError('Use a fresh power-request record; do not hide a prior interruption')
    data = dict(
        schema_version='local-process-idle-sleep-request-v1',
        started_at=now().isoformat(), process_id=os.getpid(), command=command,
        automatic_idle_sleep_request=False, display_required=False,
        manual_lid_or_button_sleep_prevented=False, global_power_plan_changed=False,
        heartbeat_gaps=[], status='starting',
        source='https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate',
    )
    set_state = None
    previous = None
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        set_state = kernel.SetThreadExecutionState
        set_state.argtypes = [ctypes.c_uint32]
        set_state.restype = ctypes.c_uint32
        previous = set_state(CONTINUOUS | SYSTEM_REQUIRED)
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        confirmation = set_state(CONTINUOUS | SYSTEM_REQUIRED)
        if not confirmation & SYSTEM_REQUIRED:
            set_state(previous | CONTINUOUS)
            raise RuntimeError('Calling-thread idle-sleep request could not be confirmed')
        data.update(automatic_idle_sleep_request=True, previous_thread_state=previous,
                    confirmed_thread_state=confirmation)
    data['status'] = 'running'
    child = None
    last = now()
    try:
        child = subprocess.Popen(command)
        data['child_process_id'] = child.pid
        save(record, data)
        while True:
            try:
                code = child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                code = None
            current = now()
            gap = (current-last).total_seconds()
            if gap > 90:
                data['heartbeat_gaps'].append(dict(previous=last.isoformat(), current=current.isoformat(), elapsed_seconds=round(gap, 3), classification='host_or_scheduler_gap_not_automatically_a_model_error'))
            last = current
            data['last_heartbeat_at'] = current.isoformat()
            save(record, data)
            if code is not None:
                data.update(status='completed' if code == 0 else 'command_failed', returncode=code)
                return code
    except BaseException as exc:
        data.update(status='wrapper_interrupted', exception_type=type(exc).__name__)
        raise
    finally:
        if set_state is not None:
            restored = set_state(previous | CONTINUOUS)
            data['thread_request_restored'] = bool(restored)
        data['finished_at'] = now().isoformat()
        if child is not None:
            data['child_returncode_at_wrapper_exit'] = child.poll()
        save(record, data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == '--' else args.command
    if not command:
        parser.error('A command after -- is required')
    sys.exit(run(command, args.record.resolve()))
