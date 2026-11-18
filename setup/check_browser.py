#!/usr/bin/env python3
"""可选浏览器验收。检查真实网页、教学图与file://静态页，不调用DeepSeek。"""
from pathlib import Path
import argparse
import json
import os
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def check(url='http://127.0.0.1:8000',executable=None):
    candidates=[Path(executable)] if executable else []
    candidates += list((ROOT/'runtime/browsers').glob('chromium*/**/chrome-headless-shell'))
    candidates += list(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
    browser_path=next((p for p in candidates if p.is_file()),None)
    output=ROOT/'outputs/screenshots';output.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=str(browser_path) if browser_path else None,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url,wait_until='networkidle')
        page.evaluate('document.fonts.ready')
        assert page.title()=='3DR · Knowledge Lab'
        assert page.locator('#stats .stat').count()==4
        page.screenshot(path=str(output/'overview.png'),full_page=True)
        for route in ['papers','classification','prediction','generation']:
            page.locator(f'nav a[data-page="{route}"]').click()
            expect(page.locator('#'+route)).to_be_visible()
        page.locator('#teaching-button').click()
        page.wait_for_function("document.querySelector('#graph-source').textContent.includes('教学')")
        page.wait_for_timeout(700)
        assert page.evaluate('cy.nodes().length')==31
        assert page.evaluate('cy.edges().length')==60
        page.evaluate("cy.edges()[0].emit('tap')")
        assert 'PDF' in page.locator('#graph-detail').inner_text()
        page.screenshot(path=str(output/'teaching_graph.png'),full_page=True)
        page.locator('#local-case').click()
        assert page.evaluate("cy.nodes().filter(n=>n.data('type')==='Paper').length")==3
        page.screenshot(path=str(output/'local_case.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.goto(url+'/#papers',wait_until='networkidle')
        page.screenshot(path=str(output/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
        offline=browser.new_context(offline=True,viewport={'width':1440,'height':1000})
        static=offline.new_page()
        static.on('pageerror',lambda error:errors.append(str(error)))
        static.goto((ROOT/'outputs/demo/index.html').as_uri(),wait_until='load')
        static.wait_for_timeout(400)
        assert static.locator('#connection').inner_text().startswith('静态')
        static.locator('#teaching-button').click()
        static.wait_for_function("document.querySelector('#graph-source').textContent.includes('教学')")
        assert static.evaluate('cy.nodes().length')==31
        static.locator('nav a[data-page="classification"]').click()
        static.locator('#classification-advanced > summary').click()
        static.locator('[data-run="classification"]').click()
        assert '静态' in static.locator('#toast').inner_text()
        static.screenshot(path=str(output/'offline.png'),full_page=True)
        browser.close()
    if errors:raise AssertionError(errors)
    result={'live_pages':6,'teaching_graph_nodes':31,'teaching_graph_edges':60,
            'offline_file_html':True,'mobile_no_horizontal_overflow':True,'page_errors':errors}
    (ROOT/'outputs/browser_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--executable',help='可选，已安装Chromium headless路径')
    args=parser.parse_args()
    check(args.url,args.executable)
