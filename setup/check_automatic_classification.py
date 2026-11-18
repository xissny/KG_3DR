#!/usr/bin/env python3
"""真实浏览器验收：隔离数据、模拟DeepSeek，覆盖主流程与静态浏览。"""
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
from src.classification import automatic as auto
from src.graph import export
from src.common.storage import write_json, read_json


def check():
    with tempfile.TemporaryDirectory(prefix='kg-auto-browser-') as directory:
        temporary = Path(directory)
        data, exp, output = temporary / 'data', temporary / 'experiments', temporary / 'outputs'
        shutil.copytree(ROOT / 'examples/workspace/data', data)
        exp.mkdir()
        # 清空金标准，证明主流程不以标注为前提。
        write_json(data / 'labels.json', {})
        errors = []
        executable = next(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
        with patch.object(backend, 'DATA', data), patch.object(backend, 'EXP', exp), patch.object(auto, 'DATA', data), patch.object(auto, 'EXP', exp), patch.object(auto, 'chat_json', fake_chat), patch('src.graph.store.DATA', data), patch('src.classification.history.DATA', data), patch('src.classification.history.EXP', exp), patch('backend.jobs.DATA', data), patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'browser-test-only'}), test_server() as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1050})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + '/#classification', wait_until='networkidle')
            expect(page.locator('#auto-papers-body tr')).to_have_count(12)
            assert not page.locator('#classification-advanced').get_attribute('open')
            page.locator('#auto-classify-all').click()
            page.wait_for_function("automaticUI.data?.result?.status==='complete'", timeout=30000)
            expect(page.locator('[data-auto-detail]')).to_have_count(12)
            assert read_json(data / 'labels.json') == {}
            # 类别筛选，明确关系和推断标识。
            assert page.locator('.auto-tag.direct').count() and page.locator('.auto-tag.inferred').count()
            checkbox = page.locator('[data-auto-category][data-auto-dimension="topic"]').first
            checkbox.check()
            expect(page.locator('#auto-papers-body tr')).to_have_count(12)
            page.locator('#auto-search').fill('P001')
            expect(page.locator('#auto-papers-body tr')).to_have_count(1)
            page.locator('[data-auto-detail="P001"]').click()
            expect(page.locator('#auto-detail-dialog')).to_be_visible()
            assert page.locator('.auto-assignment blockquote').count()
            page.locator('#auto-edit-correction').click()
            page.locator('[data-auto-correction]').first.uncheck()
            page.locator('#auto-correction-note').fill('浏览器可选修订测试')
            page.locator('#auto-save-correction').click()
            expect(page.locator('#auto-reset-correction')).to_be_visible()
            assert read_json(exp / 'classification_corrections.json')['P001']['note'] == '浏览器可选修订测试'
            page.locator('#auto-reset-correction').click()
            expect(page.locator('#auto-reset-correction')).to_have_count(0)
            page.locator('#auto-detail-close').click()
            page.locator('#auto-clear-filters').click()
            page.reload(wait_until='networkidle')
            expect(page.locator('#auto-papers-body tr')).to_have_count(12)
            assert page.locator('.auto-tag.inferred').count()
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path='/tmp/kg-auto-mobile.png')
            page.set_viewport_size({'width': 1440, 'height': 1050})
            page.screenshot(path='/tmp/kg-auto-desktop.png')
            # 静态导出也包含结果、筛选和证据，且不能修改。
            shutil.copytree(ROOT / 'frontend', temporary / 'frontend')
            with patch.object(export, 'ROOT', temporary), patch.object(export, 'DATA', data), patch.object(export, 'EXP', exp), patch('src.review.service.DATA', data):
                export.export_demo()
            page.goto((output / 'demo/index.html').as_uri() + '#classification', wait_until='load')
            expect(page.locator('#auto-papers-body tr')).to_have_count(12)
            expect(page.locator('#auto-classify-all')).to_be_disabled()
            page.locator('[data-auto-detail="P001"]').click()
            assert page.locator('.auto-assignment blockquote').count()
            expect(page.locator('#auto-edit-correction')).to_be_disabled()
            assert not errors, errors
            browser.close()
            print(json.dumps({'papers': 12, 'zero_gold_labels': True, 'batch_filter_evidence_correction_reload': 'passed', 'mobile_no_overflow': True, 'static_results_readonly': True, 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    check()
