"""Exercise rotation against command doubles and a synthetic configuration only."""
import json
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'ops/bin/am-rotate-secrets.sh'


@pytest.mark.parametrize('mode', ['ok', 'failed', 'unreadable', 'unreadable_zero_exit', 'missing_summary', 'admin_unhealthy'])
def test_rotation_owner_execution_consumers_and_status(tmp_path, mode):
    repo = tmp_path / 'repo'
    (repo / 'backend/app').mkdir(parents=True)
    (repo / 'backend/app/config.py').write_text('encryption_key_previous = ""\n')
    config = repo / '.env'  # Synthetic fixture; never the checkout's configuration.
    original = 'JWT_SECRET_KEY=test-jwt\nMCP_JWT_SECRET=test-mcp\nENCRYPTION_KEY=test-old-key\n'
    config.write_text(original)
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    command_log = tmp_path / 'commands.jsonl'
    double = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
with open(os.environ['TEST_COMMAND_LOG'], 'a') as output:
    output.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')
mode = os.environ['TEST_ROTATION_MODE']
if Path(sys.argv[0]).name == 'docker':
    assert sys.argv[1] == 'inspect', sys.argv
    print('unhealthy' if mode == 'admin_unhealthy' and sys.argv[-1] == 'finance-admin' else 'healthy')
elif 'run' in sys.argv:
    if mode == 'failed':
        print('owner maintenance failed', file=sys.stderr)
        sys.exit(2)
    if mode == 'missing_summary':
        print('unexpected output')
    else:
        print('applied: rotated=2 unreadable=' + ('1' if mode.startswith('unreadable') else '0'))
        sys.exit(1 if mode == 'unreadable' else 0)
'''
    for name in ('docker', 'mock-compose'):
        path = binaries / name
        path.write_text(double)
        path.chmod(0o755)
    sleep = binaries / 'sleep'
    sleep.write_text('#!/bin/sh\nexit 0\n')
    sleep.chmod(0o755)
    state = tmp_path / 'state'
    env = {
        **os.environ,
        'PATH': f'{binaries}:{os.environ["PATH"]}',
        'AM_REPO_DIR': str(repo),
        'AM_COMPOSE': f'{binaries / "mock-compose"} --project-name rehearsal',
        'AM_OPS_CONFIG': str(tmp_path / 'absent-ops-config'),
        'AM_STATE_DIR': str(state),
        'AM_BACKUP_ROOT': str(tmp_path / 'backups'),
        'AM_OPS_LOG': str(state / 'ops.log'),
        'AM_BACKEND_CONTAINER': 'finance-backend',
        'AM_ADMIN_CONTAINER': 'finance-admin',
        'TEST_COMMAND_LOG': str(command_log),
        'TEST_ROTATION_MODE': mode,
    }
    result = subprocess.run(['bash', str(SCRIPT), '--apply', '--all', '--force'], env=env,
                            capture_output=True, text=True, timeout=30)
    commands = [json.loads(line) for line in command_log.read_text().splitlines()]
    compose = [args for args in commands if args[0] == 'mock-compose']
    up = ['mock-compose', '--project-name', 'rehearsal', 'up', '-d', 'backend', 'mcp', 'admin']
    assert compose[0] == up
    assert any(args[0] == 'docker' and args[-1] == 'finance-admin' for args in commands)
    status = json.loads((state / 'status/rotate-secrets.json').read_text())
    if mode == 'admin_unhealthy':
        assert result.returncode == 1
        assert status['last_result'] == 'rolled_back'
        assert status['last_error'] == 'backend_or_admin_not_healthy'
        assert compose == [up, up]
        assert config.read_text() == original
        return
    assert compose[1:] == [[
        'mock-compose', '--project-name', 'rehearsal', 'run', '--rm', '--no-deps', 'migrate',
        'python', '-m', 'app.maintenance.reencrypt_secrets', '--apply',
    ]]
    assert 'ENCRYPTION_KEY_PREVIOUS=test-old-key' in config.read_text()
    assert '\nENCRYPTION_KEY=test-old-key\n' not in config.read_text()
    if mode == 'ok':
        assert result.returncode == 0, result.stderr
        assert status['last_result'] == 'ok' and status['last_error'] == ''
    else:
        assert result.returncode == 1
        assert status['last_result'] == 'reencrypt_incomplete'
        assert status['last_error'].startswith('exit=')
        assert ('owner maintenance failed' if mode == 'failed' else
                'unexpected output' if mode == 'missing_summary' else 'unreadable=1') in status['last_error']
        assert 'ENCRYPTION_KEY_PREVIOUS must stay' in result.stderr
