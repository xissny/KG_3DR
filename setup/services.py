#!/usr/bin/env python3
"""仅管理本项目进程。端口冲突时停止启动，不结束其他程序。"""
from pathlib import Path
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.common.storage import ROOT, now, read_json, write_json
RUNTIME = ROOT / 'runtime'


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def settings():
    return {**os.environ, 'JAVA_HOME': str(RUNTIME / 'java')}


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def start():
    RUNTIME.mkdir(exist_ok=True)
    web_port = int(os.getenv('DEMO_PORT', '8000'))
    bolt_port = int(os.getenv('NEO4J_BOLT_PORT', '7687'))
    http_port = int(os.getenv('NEO4J_HTTP_PORT', '7474'))
    neo = RUNTIME / 'neo4j/bin/neo4j'
    if not neo.exists():
        raise ValueError('请先执行 setup/install.py')
    neo_status = subprocess.run([str(neo), 'status'], env=settings(), capture_output=True).returncode
    if neo_status != 0:
        if port_open(bolt_port) or port_open(http_port):
            raise ValueError('Neo4j 端口被占用，请修改 .env 后重新运行安装脚本同步配置')
        subprocess.run([str(neo), 'start'], env=settings(), check=True, start_new_session=True)
    deadline = time.monotonic() + 55
    while not port_open(bolt_port) and time.monotonic() < deadline:
        time.sleep(1)
    if not port_open(bolt_port):
        raise ValueError('Neo4j 启动超时，检查 runtime/neo4j/logs')
    record = read_json(RUNTIME / 'web.pid.json', {})
    if record and alive(record['pid']):
        print('Demo 已在运行')
        return
    if port_open(web_port):
        raise ValueError('Demo 端口被其他进程占用')
    with (RUNTIME / 'web.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1',
                                    '--port', str(web_port)], cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    write_json(RUNTIME / 'web.pid.json', {'pid': process.pid, 'started_at': now()})
    for _ in range(30):
        if port_open(web_port):
            print(f'Demo: http://127.0.0.1:{web_port} | Neo4j: http://127.0.0.1:{http_port}')
            return
        if process.poll() is not None:
            break
        time.sleep(0.5)
    raise ValueError('Demo 启动失败，检查 runtime/web.log')


def stop():
    record = read_json(RUNTIME / 'web.pid.json', {})
    if record and alive(record['pid']):
        command = (Path('/proc') / str(record['pid']) / 'cmdline').read_bytes()
        if b'backend.app:app' not in command:
            raise ValueError('PID 已被复用，拒绝结束不属于本项目的进程')
        os.kill(record['pid'], signal.SIGTERM)
    (RUNTIME / 'web.pid.json').unlink(missing_ok=True)
    neo = RUNTIME / 'neo4j/bin/neo4j'
    if neo.exists():
        subprocess.run([str(neo), 'stop'], env=settings(), check=False)


def status():
    print(json.dumps({
        'demo': port_open(int(os.getenv('DEMO_PORT', '8000'))),
        'neo4j_http': port_open(int(os.getenv('NEO4J_HTTP_PORT', '7474'))),
        'neo4j_bolt': port_open(int(os.getenv('NEO4J_BOLT_PORT', '7687'))),
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    try:
        {'start': start, 'stop': stop, 'status': status}[args.action]()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
