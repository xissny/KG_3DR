#!/usr/bin/env python3
"""运行记录浏览器回归：虚构任务与模拟接口，不清除用户的真实运行记录。"""
from copy import deepcopy
from pathlib import Path
import json
import shutil
import tempfile
from urllib.parse import urlparse,unquote
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]


def check():
    long_output={'lines':[f'教学输出 {i:03d} - 用于测试滚动位置' for i in range(160)]}
    history=[
        {'id':'active','kind':'pipeline','status':'running','created_at':'2026-11-11T10:02:00Z','completed':1,'total':20,'logs':[]},
        {'id':'done','kind':'parse','status':'complete','created_at':'2026-11-11T10:01:00Z','result':deepcopy(long_output)},
        {'id':'failed','kind':'extract','status':'failed','created_at':'2026-11-11T10:00:00Z','error':'仅为虚构失败记录'},
    ]
    calls={'state':0,'delete':0,'fail_delete':False}
    def state():
        return {'papers':[],'included_count':0,'graph':{'nodes':[],'edges':[],'evidence':[]},
                'results':{},'jobs':deepcopy(history),'candidate_count':0,'approved_count':0}
    def respond(route):
        path=unquote(urlparse(route.request.url).path)
        if path=='/api/health':return route.fulfill(json={'deepseek_configured':False,'neo4j_browser':'http://localhost:7474/browser/'})
        if path=='/api/candidates':return route.fulfill(json=[])
        if path=='/api/state':
            calls['state']+=1
            return route.fulfill(json=state())
        if path=='/api/jobs' and route.request.method=='DELETE':
            calls['delete']+=1
            if calls['fail_delete']:
                calls['fail_delete']=False
                return route.fulfill(status=500,json={'detail':'虚构的清理失败，用于验证保留界面'})
            completed=[job for job in history if job['status'] in ('complete','failed','interrupted')]
            history[:]=[job for job in history if job not in completed]
            return route.fulfill(json={'cleared':len(completed),'kept_active':len(history)})
        target=(ROOT/'frontend'/(path.lstrip('/') or 'index.html')).resolve()
        if target.is_relative_to((ROOT/'frontend').resolve()) and target.is_file():return route.fulfill(path=str(target))
        return route.fulfill(status=404,body='Not in job history fixture')
    browsers=list(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
    browsers+=list((ROOT/'runtime/browsers').glob('chromium*/**/chrome-headless-shell'))
    errors=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=str(browsers[0]) if browsers else None,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.route('**/*',respond)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://job-history.test/',wait_until='networkidle')
        output=page.locator('[data-job-id="done"] details[data-job-output]')
        output.locator('summary').click()
        page.evaluate("window.savedOutput=document.querySelector('[data-job-id=done] details');window.savedPre=savedOutput.querySelector('pre');savedPre.scrollTop=150")
        count=calls['state']
        page.wait_for_timeout(4500)
        assert calls['state']>count,'没有观察到自动轮询'
        assert page.evaluate('savedOutput.open && savedOutput===document.querySelector("[data-job-id=done] details")')
        assert page.evaluate('savedPre.scrollTop')==150
        history[0]['completed']=8
        history.insert(0,{'id':'recent','kind':'validate','status':'complete',
                          'created_at':'2026-11-11T10:03:00Z','result':{'new_job':True}})
        page.evaluate('refresh()')
        assert page.evaluate('savedOutput.open && savedPre.scrollTop===150')
        assert page.evaluate('savedOutput===document.querySelector("[data-job-id=done] details")')
        done=next(job for job in history if job['id']=='done')
        done['result']['lines'].append('增加一行，输出更新时仍应保留展开与滚动位置')
        page.evaluate('refresh()')
        assert page.evaluate('savedOutput.open && savedPre.scrollTop===150')
        page.locator('#refresh-state').click()
        assert page.evaluate('savedOutput.open')
        output.locator('summary').click()
        page.wait_for_timeout(4200)
        assert page.evaluate('!savedOutput.open'),'用户手动收起后不应自动展开'
        output.locator('summary').click()
        page.locator('[data-job-id="recent"] summary').click()
        page.evaluate('refresh()')
        assert page.locator('#jobs details[open]').count()==2
        # 清理失败时，记录与展开状态保留，按钮可再次操作。
        calls['fail_delete']=True
        page.locator('#clear-jobs').click()
        expect(page.locator('#toast')).to_contain_text('清理失败')
        expect(page.locator('#clear-jobs')).to_be_enabled()
        assert page.evaluate('savedOutput.open')
        # 挂起一个旧轮询，等清理完成后再放回旧响应，旧记录也不能重新出现。
        page.evaluate('''() => {
          window.originalJobApi=api;window.holdNextState=true;
          api=async function(path,options={}) {
            const value=await originalJobApi(path,options);
            if(path==='/api/state'&&window.holdNextState) {
              window.holdNextState=false;
              return new Promise(resolve=>{window.releaseOldJobState=()=>resolve(value);});
            }
            return value;
          };
          window.oldJobRefresh=refresh();
        }''')
        page.wait_for_function("typeof window.releaseOldJobState==='function'")
        page.locator('#clear-jobs').click()
        expect(page.locator('#jobs .job-item')).to_have_count(1)
        page.evaluate('releaseOldJobState()')
        page.evaluate('oldJobRefresh')
        page.evaluate('() => { api=originalJobApi; }')
        expect(page.locator('#jobs .job-item')).to_have_count(1)
        assert page.locator('#jobs .job-item').get_attribute('data-job-id')=='active'
        expect(page.locator('#clear-jobs')).to_be_disabled()
        assert history[0]['status']=='running'
        history[0].update(status='complete',result={'finished':True})
        page.evaluate('refresh()')
        expect(page.locator('#clear-jobs')).to_be_enabled()
        page.locator('#clear-jobs').click()
        expect(page.locator('#jobs .job-item')).to_have_count(0)
        expect(page.locator('#jobs')).to_contain_text('尚无运行记录')
        expect(page.locator('#clear-jobs')).to_be_disabled()
        # 静态快照不能删服务器记录，但手动刷新也不应收起输出。
        with tempfile.TemporaryDirectory(prefix='kg-job-history-') as directory:
            target=Path(directory);shutil.copytree(ROOT/'frontend',target,dirs_exist_ok=True)
            bundle=state();bundle['jobs']=[deepcopy(done)]
            (target/'snapshot.js').write_text('window.KG_STATIC='+json.dumps(bundle,ensure_ascii=False)+';',encoding='utf-8')
            offline=browser.new_context(offline=True)
            static=offline.new_page();static.on('pageerror',lambda error:errors.append(str(error)))
            static.goto((target/'index.html').as_uri(),wait_until='load')
            expect(static.locator('#clear-jobs')).to_be_disabled()
            static.locator('[data-job-id="done"] summary').click()
            static.evaluate('refresh()')
            assert static.locator('#jobs details[open]').count()==1
            offline.close()
        browser.close()
    assert not errors,errors
    result={'automatic_refresh_keeps_open':True,'output_scroll_preserved':True,
            'new_jobs_and_result_updates_keep_open':True,'manual_collapse_preserved':True,
            'clear_finished_preserves_active':True,'failed_clear_can_retry':True,
            'static_read_only':True,'stale_poll_cannot_restore_cleared_jobs':True,'page_errors':errors}
    (ROOT/'runtime/job_history_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':check()
