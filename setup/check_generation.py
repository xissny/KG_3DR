#!/usr/bin/env python3
"""三任务浏览器验收：临时语料、模拟模型、临时静态快照，不调用正式数据库/API。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import argparse
import json
import os
import shutil
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(output=None):
    with TemporaryDirectory(prefix='kg3dr-generation-') as temporary:
        folder = Path(temporary)
        shutil.copytree(ROOT / 'examples/workspace/data', folder / 'data')
        os.environ['KG3DR_DATA_DIR'] = str(folder / 'data')
        os.environ['KG3DR_EXPERIMENT_DIR'] = str(folder / 'experiments')
        from src.common.storage import DATA, EXP, read_json, write_json
        from src.generation import task
        graph = read_json(DATA / 'graph_snapshot.json')
        graph['teaching'] = False  # 仅临时测试夹具，原始教学文件不变。
        write_json(DATA / 'graph_snapshot.json', graph)
        anchor = next(n for n in graph['nodes'] if n['type'] == 'Task')
        task.live_graph = lambda: graph
        def mock_model(messages, purpose, force=False):
            if purpose.startswith('generation-baseline'):
                return {'data': {'answer': 'Synthetic control answer for browser testing.'}, 'cache_key': 'browser-mock'}
            payload = json.loads(messages[-1]['content'])
            fact = payload['facts'][0]
            return {'data': {'claims': [{'id': 'C1', 'text': '浏览器测试夹具结论，仅用于验证证据交互。',
                             'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_ids'][0]]}],
                            'sections': [{'title': '测试章节', 'claim_ids': ['C1']}],
                            'suggestions': [{'text': '测试后续验证建议', 'claim_ids': ['C1'],
                                             'reasoning': '依据测试结论设计验证', 'uncertainty': '需要进一步实验'}],
                            'limitations': '模拟测试，不是正式研究结果。'}, 'cache_key': 'browser-mock'}
        task.chat_json = mock_model
        questions = [{'id': f'{kind}{i}', 'question': '围绕所选任务进行证据分析', 'task_type': kind,
                      'entity_ids': [anchor['id']], 'paper_ids': graph['paper_ids'][:2], 'reference_points': ['测试参考要点'], 'expected_fact_ids': []}
                     for kind in task.TASKS for i in range(6)]
        write_json(DATA / 'generation_questions.json', questions)
        from backend.app import app
        import uvicorn
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
        thread = Thread(target=server.run, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                if server.started: break
                time.sleep(.05)
            if not server.started: raise RuntimeError('临时服务未启动')
            from playwright.sync_api import sync_playwright, expect
            candidates = list((ROOT / 'runtime/browsers').glob('chromium*/**/chrome-headless-shell'))
            candidates += list(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
            executable = next((p for p in candidates if p.is_file()), None)
            errors = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(executable) if executable else None, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width':1440, 'height':1050})
                page.on('pageerror', lambda error: errors.append(str(error)))
                submissions=[]
                page.on('request', lambda request: submissions.append(request.post_data_json) if request.method=='POST' and request.url.endswith('/api/run') else None)
                page.goto(url + '/#generation', wait_until='networkidle')
                expect(page.locator('#generation h1')).to_have_text('基于图谱的问答与研究综述')
                expect(page.locator('[data-question-template]')).to_have_count(8)
                methods = [n for n in graph['nodes'] if n['type'] == 'Method']
                method, other = methods[:2]
                page.locator('[data-question-template=components]').click()
                expect(page.locator('#question')).to_have_value('')
                expect(page.locator('[data-template-entity]')).to_have_count(1)
                expect(page.locator('#generation-anchor-controls')).not_to_be_visible()
                page.locator('[data-template-entity="0"]').select_option(method['id'])
                expect(page.locator('#question')).to_have_value(f'“{method["name"]}”采用了哪些技术组件？请逐项列出支撑事实和论文来源。')
                assert page.evaluate('[...generationEntities]') == [method['id']]
                page.locator('[data-template-entity="0"]').select_option(other['id'])
                assert other['name'] in page.locator('#question').input_value()
                page.locator('[data-question-template=compare]').click()
                expect(page.locator('#question')).to_have_value('')
                expect(page.locator('[data-template-entity]')).to_have_count(2)
                page.locator('[data-template-entity="0"]').select_option(method['id'])
                expect(page.locator('#question')).to_have_value('')
                expect(page.locator(f'[data-template-entity="1"] option[value="{method["id"]}"]')).to_have_attribute('disabled', '')
                page.locator('[data-template-entity="1"]').select_option(other['id'])
                assert page.evaluate('[...generationEntities]') == [method['id'],other['id']]
                assert all(n['name'] in page.locator('#question').input_value() for n in (method,other))
                page.locator('[data-template-entity="1"]').select_option('')
                expect(page.locator('#question')).to_have_value('')
                page.locator('#ask-button').click()
                expect(page.locator('#generation-input-error')).to_contain_text('选择模板要求的实体')
                page.locator('[data-template-entity="1"]').select_option(other['id'])
                page.locator('#question').fill('自行修改的问题应当保留')
                page.locator('#refresh-state').click()
                expect(page.locator('#question')).to_have_value('自行修改的问题应当保留')
                expect(page.locator('#generation-output .claim')).to_have_count(0)
                page.locator('[data-question-template=task-methods]').click()
                expect(page.locator('[data-template-entity="0"] option')).to_have_count(1+len([n for n in graph['nodes'] if n['type']=='Task']))
                page.locator('[data-template-entity="0"]').select_option(anchor['id'])
                assert anchor['name'] in page.locator('#question').input_value()
                page.locator('#generation-custom-question').click()
                expect(page.locator('#generation-anchor-controls')).to_be_visible()
                while page.locator('#generation-entities input:checked').count():
                    page.locator('#generation-entities input:checked').first.uncheck()
                page.locator('[data-generation-task=summary]').click()
                expect(page.locator('#generation-template-panel')).not_to_be_visible()
                expect(page.locator('#question')).not_to_be_visible()
                expect(page.locator('#generation-anchor-controls')).not_to_be_visible()
                page.locator('#ask-button').click()
                expect(page.locator('#generation-input-error')).to_contain_text('至少选择一篇论文')
                for pid in graph['paper_ids'][:2]:
                    page.locator(f'#generation-papers input[value="{pid}"]').check()
                page.locator('[data-generation-task=qa]').click()
                page.locator('#question').fill('浏览器隔离测试')
                page.locator(f'#generation-entities input[value="{anchor["id"]}"]').check()
                interactive_run_ids={}
                for kind, label in [('qa','问题回答'), ('summary','主题总结'), ('review','研究方向综述')]:
                    page.locator(f'[data-generation-task={kind}]').click()
                    assert all(word in page.locator('#generation-guide').inner_text() for word in ('输入','输出','图谱如何参与','如何评价'))
                    if kind!='qa':
                        expect(page.locator('#question')).not_to_be_visible()
                        expect(page.locator('#generation-anchor-controls')).not_to_be_visible()
                        page.evaluate("document.querySelector('#question').value=''")
                    page.locator('#ask-button').click()
                    expect(page.locator('#generation-output .micro')).to_contain_text(label, timeout=15000)
                    if kind!='qa':
                        sent=next(payload for payload in reversed(submissions) if payload.get('stage')=='ask')
                        assert sent['task_type']==kind and sent['paper_ids']==graph['paper_ids'][:2]
                        assert 'question' not in sent and 'entity_ids' not in sent
                    interactive_run_ids[kind]=page.evaluate('state.results.generation_by_task[generationTask].run_id')
                    page.locator('#generation-output .claim summary').first.click()
                    expect(page.locator('#generation-output blockquote').first).to_be_visible()
                    expect(page.locator('#generation-output a[href^="/api/pdf/"]').first).to_have_attribute('href', __import__('re').compile(r'#page=\d+'))
                for kind, label in [('qa','问题回答'), ('summary','主题总结'), ('review','研究方向综述')]:
                    page.locator(f'[data-generation-task={kind}]').click()
                    expect(page.locator('#generation-output .micro')).to_contain_text(label)
                    assert page.evaluate('state.results.generation_by_task[generationTask].run_id') == interactive_run_ids[kind]
                page.reload(wait_until='networkidle')
                expect(page.locator('#generation-output .micro')).to_contain_text('问题回答')
                page.locator('[data-generation-task=review]').click()
                expect(page.locator('.generation-suggestions')).to_contain_text('待验证问题')
                page.locator('[data-claim-link]').first.click()
                assert page.url.endswith('#generation')
                page.locator('#generation-subgraph > summary').click()
                page.wait_for_function('generationCy && generationCy.nodes().length > 0')
                page.locator('#generation-advanced > summary').click()
                page.locator('#edit-questions').click()
                expect(page.locator('.generation-question-row')).to_have_count(18)
                page.locator('#editor-form button[type=submit]').click()
                expect(page.locator('#editor-dialog')).not_to_be_visible()
                page.locator('[data-run=generation_eval]').click()
                expect(page.locator('#generation-eval-output')).to_contain_text('18 道题', timeout=15000)
                assert page.evaluate('Object.fromEntries(Object.entries(state.results.generation_by_task).map(([k,v])=>[k,v.run_id]))') == interactive_run_ids
                page.locator('#review-generation').click()
                expect(page.locator('.generation-review-case')).to_have_count(18)
                page.locator('.generation-review-fields [data-score=correct]').first.select_option('true')
                page.locator('#editor-form button[type=submit]').click()
                expect(page.locator('#editor-dialog')).not_to_be_visible()
                saved = read_json(EXP / 'generation_evaluation.json')
                assert saved['metrics']['reviewed'] + saved['metrics']['baseline']['reviewed'] == 1
                page.locator('[data-generation-task=qa]').click()
                page.locator('[data-question-template=compare]').click()
                page.locator('[data-template-entity="0"]').select_option(method['id'])
                page.locator('[data-template-entity="1"]').select_option(other['id'])
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                if output:
                    destination=Path(output);destination.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(destination/'generation-mobile.png'),full_page=True)
                # 构造独立静态包，仅复制前端和临时测试产物，完全不重导出正式成果。
                static = folder / 'demo'
                shutil.copytree(ROOT / 'frontend', static)
                bundle = page.evaluate('JSON.parse(JSON.stringify(state))')
                bundle['jobs'] = []
                (static / 'snapshot.js').write_text('window.KG_STATIC=' + json.dumps(bundle, ensure_ascii=False).replace('<', '\\u003c') + ';', encoding='utf-8')
                offline = browser.new_context(offline=True, viewport={'width':1440,'height':1000})
                static_page = offline.new_page()
                static_page.on('pageerror', lambda error: errors.append(str(error)))
                static_page.goto((static/'index.html').as_uri()+'#generation', wait_until='load')
                expect(static_page.locator('#generation-output')).to_contain_text('浏览器测试夹具结论')
                for kind, label in [('qa','问题回答'), ('summary','主题总结'), ('review','研究方向综述')]:
                    static_page.locator(f'[data-generation-task={kind}]').click()
                    expect(static_page.locator('#generation-output .micro')).to_contain_text(label)
                    assert static_page.evaluate('state.results.generation_by_task[generationTask].run_id') == interactive_run_ids[kind]
                expect(static_page.locator('#generation-output a[href^="/api/pdf/"]')).to_have_count(0)
                static_page.locator('#generation-subgraph > summary').click()
                static_page.wait_for_function('generationCy && generationCy.nodes().length > 0')
                static_page.locator('#ask-button').click()
                expect(static_page.locator('#toast')).to_contain_text('静态')
                if output: static_page.screenshot(path=str(Path(output)/'generation-offline.png'),full_page=True)
                browser.close()
            if errors: raise AssertionError(errors)
            result={'separate_outputs_and_reload':True,'evaluation_preserves_outputs':True,'paper_only_summary_and_review':True,'question_templates':True,'three_task_generation':True,'evidence_and_pdf_links':True,'subgraph':True,
                    'question_form_18_cases':True,'ab_review_form':True,'mobile_no_overflow':True,
                    'offline_read_only':True,'page_errors':errors,'data':'temporary fixtures and mock model only'}
            if output: (Path(output)/'generation-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            server.should_exit = True
            thread.join(timeout=5)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='可选：截图及验收 JSON 输出目录')
    check(parser.parse_args().output)
