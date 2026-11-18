#!/usr/bin/env python3
"""隔离浏览器验收：多关系预测、刷新恢复、详情、旧版本、静态导出。"""
from contextlib import ExitStack
from pathlib import Path
import json
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from setup.check_label_review import test_server
from test_relation_prediction import discovery_graph
import backend.app
from src.prediction import task
from src.graph import export
from src.common.storage import read_json, write_json


def check():
    with tempfile.TemporaryDirectory(prefix='kg-relations-') as directory, ExitStack() as stack:
        root = Path(directory)
        data, exp = root / 'data', root / 'experiments'
        shutil.copytree(ROOT / 'examples/workspace/data', data)
        shutil.copytree(ROOT / 'frontend', root / 'frontend')
        exp.mkdir()
        for name, module in list(sys.modules.items()):
            if name.startswith(('src.', 'backend.')):
                for attr, value in [('DATA', data), ('EXP', exp)]:
                    if hasattr(module, attr):
                        stack.enter_context(patch.object(module, attr, value))
        stack.enter_context(patch.object(export, 'ROOT', root))
        # Synthetic IDs match neither real evidence nor source papers; PDF opening is tested by link presence only.
        graph = discovery_graph()
        graph['nodes'].append({'id': 'd', 'name': 'd', 'type': 'Method'})
        graph['edges'].append({'id': 'p-d', 'source': 'p', 'relation': 'PROPOSES', 'target': 'd', 'evidence_ids': ['evidence'], 'paper_ids': ['p']})
        for i in range(25):
            graph['nodes'].append({'id': f'c{i:02}', 'name': f'Extra component {i}', 'type': 'Component'})
            graph['edges'].append({'id': f'x{i}', 'source': 'b', 'relation': 'USES_COMPONENT', 'target': f'c{i:02}', 'evidence_ids': ['evidence'], 'paper_ids': ['p']})
        write_json(data / 'graph_snapshot.json', graph)
        original = (data / 'graph_snapshot.json').read_bytes()
        errors = []
        executable = next(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
        with test_server() as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + '/#prediction', wait_until='networkidle')
            expect(page.locator('#relation-run')).to_be_enabled()
            expect(page.locator('#prediction-advanced')).not_to_have_attribute('open', '')
            page.locator('#relation-run').click()
            expect(page.locator('#relation-results tbody tr').first).to_be_visible(timeout=20000)
            expect(page.locator('#relation-results tbody tr')).to_have_count(20)
            page.locator('#relation-next').click()
            expect(page.locator('#relation-pagination')).to_contain_text('2 /')
            page.locator('#relation-result-type').select_option('USES_COMPONENT')
            page.locator('#relation-results button').first.click()
            expect(page.locator('#relation-detail')).to_contain_text('Synthetic evidence')
            expect(page.locator('#relation-detail a').first).to_have_attribute('href', '/api/pdf/p#page=1')
            assert page.evaluate('relationCy.edges(".predicted").length') == 1
            assert page.evaluate('relationCy.nodes().length') > 1
            page.screenshot(path='/tmp/kg-relations-desktop.png', full_page=True)
            # Details and filters survive an unrelated state revision.
            write_json(exp / 'unrelated.json', {'test': True})
            page.evaluate('refresh()')
            expect(page.locator('#relation-detail')).to_contain_text('Synthetic evidence')
            page.locator('#relation-result-search').fill('no such entity')
            expect(page.locator('#relation-results')).to_contain_text('没有匹配')
            page.reload(wait_until='networkidle')
            expect(page.locator('#relation-results tbody tr').first).to_be_visible()
            page.locator('#relation-mode').select_option('single')
            page.locator('#relation-source-search').fill('a')
            page.locator('#relation-source').select_option('a')
            page.locator('#relation-run').click()
            expect(page.locator('#relation-result-count')).to_contain_text('单实体', timeout=20000)
            result = read_json(exp / 'relation_prediction.json')
            assert all(c['source_id'] == 'a' for c in result['candidates'])
            assert (data / 'graph_snapshot.json').read_bytes() == original
            graph['version'] = 'v2'
            write_json(data / 'graph_snapshot.json', graph)
            page.reload(wait_until='networkidle')
            expect(page.locator('#relation-version-notice')).to_contain_text('旧图谱版本')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#relation-results button').first.click()
            expect(page.locator('#relation-detail')).to_contain_text('Synthetic evidence')
            assert page.locator('#relation-detail a').count() == 0
            page.screenshot(path='/tmp/kg-relations-mobile.png', full_page=True)
            # Export into the temporary root, then load as a file exactly as end users do.
            exported = export.export_demo()
            bundle = Path(exported['demo']).parent / 'snapshot.js'
            assert 'relation_prediction' in bundle.read_text()
            page.goto(Path(exported['demo']).as_uri() + '#prediction', wait_until='networkidle')
            expect(page.locator('#relation-run')).to_be_disabled()
            expect(page.locator('#relation-results tbody tr').first).to_be_visible()
            page.locator('#relation-results button').first.click()
            expect(page.locator('#relation-detail')).to_contain_text('Synthetic evidence')
            assert page.locator('#relation-detail a').count() == 0
            assert not errors, errors
            browser.close()
        print(json.dumps({'browser': 'passed', 'static_export': 'passed', 'mobile': 'passed'}, ensure_ascii=False))


if __name__ == '__main__':
    check()
