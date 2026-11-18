#!/usr/bin/env python3
"""服务器安装入口：可重复执行，不改动系统 Java 和已有 Conda 环境。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime'
DOWNLOADS = RUNTIME / 'downloads'
ENV = ROOT / '.conda/kg3dr'


def download(url, filename):
    target = DOWNLOADS / filename
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + '.part')
        print(f'下载 {filename}', flush=True)
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'KG3DR-Course/1.0'})
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open('wb') as output:
                    shutil.copyfileobj(response, output)
                temporary.replace(target)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return target


def unpack(archive, destination):
    if destination.exists():
        return
    staging = destination.with_name(destination.name + '-extracting')
    staging.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        # 仅接受在 staging 下的路径和安全符号链接，兼容 JDK 的内部链接。
        for member in tar.getmembers():
            location = (staging / member.name).resolve()
            if not location.is_relative_to(staging.resolve()):
                raise ValueError('安装包包含非法路径')
            if member.issym() and not (location.parent / member.linkname).resolve().is_relative_to(staging.resolve()):
                raise ValueError('安装包包含非法链接')
        tar.extractall(staging)
    children = list(staging.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise ValueError('安装包顶层结构异常')
    children[0].rename(destination)
    staging.rmdir()


def install(skip_environment=False):
    RUNTIME.mkdir(exist_ok=True)
    if not skip_environment:
        conda = shutil.which('conda') or '/root/miniconda3/bin/conda'
        if not (ENV / 'bin/python').exists():
            subprocess.run([conda, 'create', '--prefix', str(ENV), 'python=3.11', 'pip', '-y',
                            '--override-channels', '-c', 'https://repo.anaconda.com/pkgs/main'], check=True)
        version = subprocess.check_output([str(ENV / 'bin/python'), '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'], text=True).strip()
        if version != '3.11':
            raise ValueError('已有项目环境不是 Python 3.11，请检查，不会自动删除')
        subprocess.run([str(ENV / 'bin/python'), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    sources = {
        'java': ('https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse', 'java21.tar.gz'),
        'neo4j': ('https://dist.neo4j.org/neo4j-community-5.26.0-unix.tar.gz', 'neo4j-5.26.0.tar.gz'),
        'cytoscape': ('https://cdn.jsdelivr.net/npm/cytoscape@3.30.4/dist/cytoscape.min.js', 'cytoscape-3.30.4.min.js'),
        'font': ('https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf', 'NotoSansCJKsc-Regular.otf'),
    }
    records = []
    for name, (url, filename) in sources.items():
        file = download(url, filename)
        records.append({'name': name, 'url': url, 'filename': filename,
                        'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
        if name in ('java', 'neo4j'):
            unpack(file, RUNTIME / name)
        if name == 'font':
            vendor = ROOT / 'frontend/vendor'
            vendor.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, vendor / 'NotoSansCJKsc-Regular.otf')
        if name == 'cytoscape':
            vendor = ROOT / 'frontend/vendor'
            vendor.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, vendor / 'cytoscape.min.js')
    env_file = ROOT / '.env'
    if not env_file.exists():
        content = (ROOT / '.env.example').read_text()
        content = content.replace('NEO4J_PASSWORD=\n', 'NEO4J_PASSWORD=' + secrets.token_urlsafe(24) + '\n')
        env_file.write_text(content)
        env_file.chmod(0o600)
    config = dict(line.split('=', 1) for line in env_file.read_text().splitlines() if '=' in line and not line.startswith('#'))
    bolt = config.get('NEO4J_BOLT_PORT', '7687')
    http = config.get('NEO4J_HTTP_PORT', '7474')
    conf = RUNTIME / 'neo4j/conf/neo4j.conf'
    conf.write_text('\n'.join([
        'server.default_listen_address=127.0.0.1', 'server.default_advertised_address=localhost',
        'server.bolt.enabled=true', f'server.bolt.listen_address=127.0.0.1:{bolt}',
        f'server.bolt.advertised_address=localhost:{bolt}',
        'server.http.enabled=true', f'server.http.listen_address=127.0.0.1:{http}',
        f'server.http.advertised_address=localhost:{http}', 'server.https.enabled=false',
        'server.memory.heap.initial_size=256m', 'server.memory.heap.max_size=512m',
        'server.memory.pagecache.size=256m', 'dbms.security.auth_enabled=true',
    ]) + '\n')
    marker = RUNTIME / 'neo4j/.auth-initialized'
    if not marker.exists():
        java_env = {**os.environ, 'JAVA_HOME': str(RUNTIME / 'java')}
        # 密码通过环境加载到子进程；不打印命令或密码。
        subprocess.run([str(RUNTIME / 'neo4j/bin/neo4j-admin'), 'dbms', 'set-initial-password', config['NEO4J_PASSWORD']],
                       env=java_env, check=True, stdout=subprocess.DEVNULL)
        marker.touch()
    (RUNTIME / 'installation.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
    if (ENV / 'bin/python').exists():
        lock = subprocess.check_output([str(ENV / 'bin/python'), '-m', 'pip', 'freeze'], text=True)
        (ROOT / 'requirements-lock.txt').write_text(lock)
    print('安装完成。连接参数保存在 .env；请勿公开该文件。', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-environment', action='store_true', help='环境已安装时只部署服务依赖')
    args = parser.parse_args()
    install(args.skip_environment)
