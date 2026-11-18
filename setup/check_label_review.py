"""隔离教学数据验证标签审核交互，不写入正式数据。"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contextlib import contextmanager
from threading import Thread
import socket
import time
import uvicorn
from playwright.sync_api import sync_playwright, expect
from backend.app import app
import backend.app as backend
from src.common.storage import read_json


@contextmanager
def test_server():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started, '临时服务未启动'
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def check():
    with tempfile.TemporaryDirectory(prefix='kg-label-review-') as temporary:
        data = Path(temporary) / 'data'
        shutil.copytree(ROOT / 'examples/workspace/data', data)
        exp = Path(temporary) / 'experiments'
        exp.mkdir()
        errors = []
        executable = next(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'), None)
        with patch.object(backend, 'DATA', data), patch.object(backend, 'EXP', exp), patch('src.graph.store.DATA', data), patch('src.classification.history.DATA', data), patch('src.classification.history.EXP', exp), patch('src.classification.automatic.DATA', data), patch('src.classification.automatic.EXP', exp), patch('backend.jobs.DATA', data), test_server() as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable) if executable else None, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1360, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url+'/#classification', wait_until='networkidle')
            page.locator('#classification-advanced > summary').click()
            page.locator('#edit-labels').click()
            expect(page.locator('#label-review')).to_be_visible()
            cards = page.locator('[data-label-paper]')
            assert cards.count() == 12
            card = cards.first
            paper_id = card.get_attribute('data-label-paper')
            card.locator('details summary').click()
            options = card.locator('[data-label-task]')
            checkbox = options.first
            task = checkbox.get_attribute('data-label-task')
            checkbox.set_checked(True)
            expect(card.locator(f'[data-label-remove="{task}"]')).to_be_visible()
            card.locator(f'[data-label-remove="{task}"]').click()
            expect(card.locator(f'[data-label-task="{task}"]')).not_to_be_checked()
            card.locator(f'[data-label-task="{task}"]').check()
            page.locator('#label-reviewer').fill('浏览器验收')
            card.locator('[data-label-confirm]').click()
            expect(card.locator('[data-label-confirm]')).to_have_text('已确认生效')
            assert read_json(data / 'labels.json')[paper_id]['reviewer'] == '浏览器验收'
            page.locator('#reload-labels').click()
            expect(page.locator(f'[data-label-paper="{paper_id}"] [data-label-task="{task}"]')).to_be_checked()
            page.locator('#label-search').fill(paper_id)
            assert page.locator('[data-label-paper]:visible').count() == 1
            # 空闲刷新保留正在编辑的内容，且不重新创建概览图。
            page.locator('#label-search').fill('')
            page.locator('nav a[data-page="overview"]').click()
            page.wait_for_timeout(100)
            page.evaluate('window.savedMiniCy=miniCy')
            page.evaluate('refresh()')
            assert page.evaluate('miniCy===window.savedMiniCy')
            page.locator('nav a[data-page="classification"]').click()
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path='/tmp/kg-label-review-mobile.png', full_page=True)
            page.set_viewport_size({'width': 1360, 'height': 1000})
            page.screenshot(path='/tmp/kg-label-review-desktop.png', full_page=True)
            assert not errors, errors
            browser.close()
            print(json.dumps({'papers': 12, 'add_remove_confirm_reload': 'passed', 'search': 'passed', 'idle_graph_reused': True, 'mobile_overflow': False, 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    check()
