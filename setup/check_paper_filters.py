#!/usr/bin/env python3
"""浏览器回归：全部请求由虚构夹具响应，绝不读写用户论文或调用DeepSeek。"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import shutil
import tempfile
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def check():
    papers = [{'paper_id':'P001','title':'界面测试论文 A（虚构）','included':True},
              {'paper_id':'P002','title':'界面测试论文 B（虚构）','included':True}]
    subject = {'id':'M','type':'Method','name':'界面测试方法'}
    obj = {'id':'C','type':'Component','name':'界面测试组件'}
    rows = [{'id':eid,'paper_id':pid,'status':status,'reviewer':'测试审核者' if status!='pending' else '',
             'note':'','candidate':{'subject':{'type':'Method','name':subject['name']},
               'relation':'USES_COMPONENT','object':{'type':'Component','name':obj['name']},
               'quote':'This is synthetic evidence used only for UI testing.','page':1}}
            for eid,pid,status in [('E1','P001','pending'),('E2','P001','approved'),
                                   ('E3','P002','pending'),('E4','P002','rejected')]]
    graph = {'nodes':[subject,obj]+[{'id':p['paper_id'],'type':'Paper','name':p['title']} for p in papers],
             'edges':[{'id':'R_shared','source':'M','target':'C','relation':'USES_COMPONENT',
                       'paper_ids':['P001','P002'],'evidence_ids':['G1','G2']},
                      {'id':'R_p1','source':'P001','target':'M','relation':'PROPOSES',
                       'paper_ids':['P001'],'evidence_ids':['G3']},
                      {'id':'R_p2','source':'P002','target':'M','relation':'PROPOSES',
                       'paper_ids':['P002'],'evidence_ids':['G4']}],
             'evidence':[{'id':eid,'paper_id':pid,'page':1,'quote':'Synthetic reviewed graph evidence.'}
                         for eid,pid in [('G1','P001'),('G2','P002'),('G3','P001'),('G4','P002')]],
             'paper_ids':['P001','P002'],'version':'ui-fixture-only'}
    mutations = []
    revision = None
    def groups():
        return [{'id':'T1','subject':subject,'object':obj,'relation':'USES_COMPONENT',
                 'rows':deepcopy(rows),'status_counts':{s:sum(r['status']==s for r in rows)
                                                       for s in ['pending','approved','rejected']}}]
    def state():
        return {'papers':papers,'included_count':2,'graph':graph,'jobs':[],'results':{},
                'candidate_count':len(rows),'approved_count':sum(r['status']=='approved' for r in rows),
                'candidate_groups':groups(),'paper_numbering_revision':revision}
    initial_snapshot = deepcopy(state())
    def respond(route):
        path = unquote(urlparse(route.request.url).path)
        if path == '/api/state': return route.fulfill(json=state())
        if path == '/api/health': return route.fulfill(json={'deepseek_configured':False,'neo4j_browser':'http://localhost:7474/browser/'})
        if path == '/api/candidates': return route.fulfill(json=groups())
        if path == '/api/graph': return route.fulfill(json=graph)
        if path == '/api/review-bulk':
            payload = route.request.post_data_json
            mutations.append(payload)
            for row in rows:
                if row['id'] in payload['ids']: row.update(status=payload['status'],reviewer=payload['reviewer'])
            return route.fulfill(json={'updated':len(payload['ids'])})
        target = (ROOT / 'frontend' / (path.lstrip('/') or 'index.html')).resolve()
        if target.is_relative_to((ROOT / 'frontend').resolve()) and target.is_file():
            return route.fulfill(path=str(target))
        return route.fulfill(status=404,body='Not in UI fixture')

    browsers = list(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
    browsers += list((ROOT/'runtime/browsers').glob('chromium*/**/chrome-headless-shell'))
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browsers[0]) if browsers else None,args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':1440,'height':1100})
        context.route('**/*',respond)
        page = context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://kg3dr.test/#graph',wait_until='networkidle')
        expect(page.locator('#facts-body .fact-check')).to_have_count(2)
        page.locator('#review-paper').select_option('P001')
        expect(page.locator('#facts-body .fact-check')).to_have_count(1)
        assert page.locator('.fact-check').input_value() == 'E1'
        page.locator('#review-approved').click()
        assert page.locator('.fact-check').input_value() == 'E2'
        page.locator('#review-rejected').click()
        expect(page.locator('#facts-body .fact-check')).to_have_count(0)
        page.locator('#review-paper').select_option('P002')
        assert page.locator('.fact-check').input_value() == 'E4'
        page.locator('#review-pending').click()
        page.locator('#reviewer').fill('界面测试审核者')
        page.locator('#select-all-facts').check()
        page.locator('#approve-selected').click()
        expect(page.locator('#facts-body .fact-check')).to_have_count(0)
        assert mutations[0]['ids'] == ['E3']
        assert next(r for r in rows if r['id']=='E1')['status'] == 'pending'
        assert next(r for r in rows if r['id']=='E4')['status'] == 'rejected'
        page.locator('#review-approved').click()
        expect(page.locator('#facts-body .fact-check')).to_have_count(1)

        page.locator('#official-graph').click()
        page.wait_for_function('cy && cy.edges().length === 3')
        page.locator('.graph-paper-check[value="P002"]').uncheck()
        assert page.evaluate('cy.edges().length') == 2
        assert page.evaluate("cy.edges().filter(e=>e.id()==='R_shared')[0].data('evidence_ids')") == ['G1']
        page.evaluate("cy.getElementById('R_shared').emit('tap')")
        assert 'P001' in page.locator('#graph-detail').inner_text()
        assert 'P002' not in page.locator('#graph-detail').inner_text()
        page.locator('#graph-papers-none').click()
        expect(page.locator('#main-graph')).to_contain_text('尚未勾选论文')
        page.reload(wait_until='networkidle')
        expect(page.locator('.graph-paper-check:checked')).to_have_count(0)
        page.locator('#graph-papers-all').click()
        assert page.evaluate('cy.edges().length') == 3
        page.locator('.graph-paper-check[value="P002"]').uncheck()
        # 编号版本变更时丢弃旧编号选择，避免旧P001指向另一篇论文。
        revision = 'ui-numbering-revision'
        page.evaluate('refresh()')
        expect(page.locator('.graph-paper-check:checked')).to_have_count(2)
        page.locator('.graph-paper-check[value="P002"]').uncheck()
        screenshot = ROOT/'outputs/screenshots/paper_filters.png'
        screenshot.parent.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(screenshot),full_page=True)

        with tempfile.TemporaryDirectory(prefix='kg3dr-filter-static-') as temporary:
            target = Path(temporary)
            shutil.copytree(ROOT/'frontend',target,dirs_exist_ok=True)
            (target/'snapshot.js').write_text('window.KG_STATIC='+json.dumps(initial_snapshot,ensure_ascii=False)+';')
            offline = browser.new_context(offline=True)
            static = offline.new_page()
            static.on('pageerror',lambda error:errors.append(str(error)))
            static.goto((target/'index.html').as_uri()+'#graph',wait_until='load')
            expect(static.locator('#facts-body .fact-check')).to_have_count(2)
            static.locator('#review-paper').select_option('P001')
            static.locator('#review-approved').click()
            assert static.locator('.fact-check').input_value() == 'E2'
            static.locator('.graph-paper-check[value="P002"]').uncheck()
            assert static.evaluate('cy.edges().length') == 2
            offline.close()
        browser.close()
    assert not errors,errors
    result={'review_paper_and_status':True,'bulk_review_visible_rows_only':True,
            'graph_selected_papers_only':True,'shared_edge_evidence_filtered':True,
            'empty_selection_and_reload':True,'offline_filters':True,'page_errors':errors}
    (ROOT/'outputs/paper_filters_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__ == '__main__': check()
