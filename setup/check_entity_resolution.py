#!/usr/bin/env python3
"""隔离浏览器验收：模拟模型、编辑候选、保存草稿、合并和静态只读。"""
from contextlib import ExitStack
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
from setup.check_label_review import test_server
from test_entity_resolution import add_variant, fake_chat
from src.common.storage import read_json
from src.review import resolution
from src.graph import export
import src.classification.automatic
import src.classification.history


def check():
    with tempfile.TemporaryDirectory(prefix='kg-entity-resolution-') as temporary, ExitStack() as stack:
        root = Path(temporary)
        data, exp = root / 'data', root / 'experiments'
        shutil.copytree(ROOT / 'examples/workspace/data', data)
        shutil.copytree(ROOT / 'frontend', root / 'frontend')
        exp.mkdir()
        # 与pytest夹具一致：所有数据模块都指向临时目录。
        for name, module in list(sys.modules.items()):
            if name.startswith(('src.', 'backend.')):
                for attr, path in [('DATA', data), ('EXP', exp)]:
                    if hasattr(module, attr):
                        stack.enter_context(patch.object(module, attr, path))
        def mixed_chat(messages, **kwargs):
            response = fake_chat(messages, **kwargs)
            groups = response['data']['groups']
            if groups:
                response['data']['groups'] = [
                    {'member_ids': groups[0]['member_ids'][:1], 'canonical_name': '单实体建议', 'reason': '无匹配'},
                    *groups,
                ]
            return response
        stack.enter_context(patch.object(resolution, 'chat_json', mixed_chat))
        stack.enter_context(patch.object(export, 'ROOT', root))
        add_variant(data)
        original = {p.name: p.read_bytes() for p in (data / 'candidates').glob('*.json')}
        official = (data / 'graph_snapshot.json').read_bytes()
        executable = next(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'), None)
        errors = []
        with test_server() as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable) if executable else None, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url + '/#graph', wait_until='networkidle')
            page.locator('#resolution-detect').click()
            card = page.locator('[data-resolution-id]').first
            expect(card).to_be_visible(timeout=20000)
            expect(page.locator('#resolution-notice')).to_contain_text('已忽略 1 条无效合并建议')
            expect(page.locator('#resolution-error')).to_be_empty()
            expect(card.locator('[data-resolution-member]:checked')).to_have_count(2)
            # 添加后可取消选择；证据可逐条展开查看。
            select = card.locator('[data-resolution-add]')
            third = select.locator('option').nth(1).get_attribute('value')
            select.select_option(third)
            expect(card.locator('[data-resolution-member]:checked')).to_have_count(3)
            card.locator(f'[data-resolution-member][value="{third}"]').uncheck()
            card.locator('[data-resolution-name]').fill('全局注意力')
            card.locator('[data-resolution-note]').fill('浏览器验收草稿')
            card.locator('[data-resolution-action="draft"]').click()
            expect(card.locator('h3')).to_contain_text('已保存草稿')
            page.reload(wait_until='networkidle')
            expect(page.locator('#resolution-notice')).to_contain_text('已忽略 1 条无效合并建议')
            card = page.locator('[data-resolution-id]').first
            expect(card.locator('[data-resolution-name]')).to_have_value('全局注意力')
            expect(card.locator('[data-resolution-member]:checked')).to_have_count(2)
            # 审核者必填。
            card.locator('[data-resolution-action="confirm"]').click()
            expect(card.locator('.resolution-error')).to_contain_text('审核者')
            page.locator('#resolution-reviewer').fill('浏览器验收')
            card.locator('[data-resolution-action="confirm"]').click()
            expect(page.locator('#resolution-list')).to_contain_text('当前筛选没有合并建议')
            page.locator('#resolution-status').select_option('confirmed')
            expect(page.locator('#resolution-list')).to_contain_text('已合并')
            assert read_json(data / 'aliases.json')['Component:global attn'] == '全局注意力'
            assert original == {p.name: p.read_bytes() for p in (data / 'candidates').glob('*.json')}
            assert (data / 'graph_snapshot.json').read_bytes() == official
            page.locator('#entity-resolution').screenshot(path='/tmp/kg-entity-resolution-desktop.png')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.locator('#entity-resolution').screenshot(path='/tmp/kg-entity-resolution-mobile.png')
            export.export_demo()
            page.goto((root / 'outputs/demo/index.html').as_uri() + '#graph', wait_until='load')
            expect(page.locator('#resolution-detect')).to_be_disabled()
            page.locator('#resolution-status').select_option('confirmed')
            expect(page.locator('[data-resolution-name]')).to_have_value('全局注意力')
            expect(page.locator('[data-resolution-name]')).to_be_disabled()
            assert not errors, errors
            browser.close()
        print(json.dumps({'candidate_add_remove': 'passed', 'draft_reload': 'passed', 'confirm': 'passed',
                          'evidence_preserved': True, 'official_graph_unchanged': True,
                          'mobile_no_overflow': True, 'static_readonly': True, 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    check()
