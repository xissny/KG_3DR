#!/usr/bin/env python3
"""隔离浏览器验收：版本查看、差异、恢复、旧结果兼容及静态只读。"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from playwright.sync_api import sync_playwright, expect
from test_automatic_classification import fake_chat
from setup.check_label_review import test_server
import backend.app as backend
from src.classification import automatic as auto, history
from src.graph import export
from src.common.storage import read_json, write_json


def check():
    with tempfile.TemporaryDirectory(prefix='kg-taxonomy-history-') as directory:
        root = Path(directory)
        data, exp = root / 'data', root / 'experiments'
        shutil.copytree(ROOT / 'examples/workspace/data', data)
        exp.mkdir()
        errors = []
        executable = next(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
        with patch.object(backend, 'DATA', data), patch.object(backend, 'EXP', exp), patch.object(auto, 'DATA', data), patch.object(auto, 'EXP', exp), patch.object(history, 'DATA', data), patch.object(history, 'EXP', exp), patch.object(auto, 'chat_json', fake_chat), patch('src.graph.store.DATA', data), patch('backend.jobs.DATA', data), patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'browser-test-key'}):
            auto.run_automatic_classification(['P001'])
            first = read_json(exp / 'classification_taxonomy.json')
            original = history.snapshot_path(first['snapshot_id']).read_bytes()
            changed = deepcopy(first)
            changed['categories'][0]['definition'] = '浏览器测试：更新后的定义'
            changed['version'] = auto.taxonomy_version(changed['categories'])
            second = history.activate_taxonomy(changed)
            with test_server() as url, sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(executable), args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1440, 'height': 1050})
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url + '/#classification', wait_until='networkidle')
                page.locator('#auto-taxonomy-history').click()
                expect(page.locator('#taxonomy-history-dialog')).to_be_visible()
                expect(page.locator('#taxonomy-history-list tbody tr')).to_have_count(2)
                expect(page.locator('#taxonomy-history-comparison')).to_contain_text('修改 1')
                page.locator('#taxonomy-history-after').select_option(first['snapshot_id'])
                expect(page.locator('#taxonomy-history-restore')).to_be_enabled()
                expect(page.locator('#taxonomy-history-detail')).to_contain_text('11 篇需要分类或重新分类')
                page.screenshot(path='/tmp/kg-taxonomy-history-desktop.png')
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('#taxonomy-history-restore').click()
                expect(page.locator('#taxonomy-history-list tbody tr')).to_have_count(3)
                current = read_json(exp / 'classification_taxonomy.json')
                assert current['version'] == first['version']
                assert history.snapshot_path(first['snapshot_id']).read_bytes() == original
                assert history.get_snapshot(current['snapshot_id'])['restored_from'] == first['snapshot_id']
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('#taxonomy-history-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
                page.screenshot(path='/tmp/kg-taxonomy-history-mobile.png')
                page.locator('#taxonomy-history-close').click()
                # 模型不再被调用；恢复后P001原分类与旧体系重新匹配。
                page.locator('#auto-status').select_option('complete')
                expect(page.locator('[data-auto-detail="P001"]')).to_be_visible()
                shutil.copytree(ROOT / 'frontend', root / 'frontend')
                with patch.object(export, 'ROOT', root), patch.object(export, 'DATA', data), patch.object(export, 'EXP', exp), patch('src.review.service.DATA', data):
                    export.export_demo()
                page.goto((root / 'outputs/demo/index.html').as_uri() + '#classification', wait_until='load')
                page.locator('#auto-taxonomy-history').click()
                expect(page.locator('#taxonomy-history-list tbody tr')).to_have_count(3)
                page.locator('#taxonomy-history-after').select_option(second['snapshot_id'])
                expect(page.locator('#taxonomy-history-restore')).to_be_disabled()
                expect(page.locator('#taxonomy-history-detail')).to_contain_text('浏览器测试：更新后的定义')
                assert not errors, errors
                browser.close()
                print(json.dumps({'history_versions': 3, 'diff_restore_impact': 'passed', 'immutable_snapshot': True, 'restore_without_model': True, 'mobile_no_overflow': True, 'static_readonly': True, 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    check()
