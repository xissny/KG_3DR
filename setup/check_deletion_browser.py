#!/usr/bin/env python3
"""使用隔离的教学PDF测试删除按钮；不连接或修改用户语料。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def check():
    with TemporaryDirectory(prefix='kg3dr-delete-ui-') as temporary:
        folder=Path(temporary)
        data=folder/'data';(data/'pdfs').mkdir(parents=True)
        papers=json.loads((ROOT/'examples/workspace/data/papers.json').read_text())[:1]
        source=Path(papers[0]['pdf_file'])
        pdf=data/'pdfs/teaching.pdf';shutil.copy2(source,pdf)
        papers[0]['pdf_file']=str(pdf)
        (data/'papers.json').write_text(json.dumps(papers))
        environment={**os.environ,'KG3DR_DATA_DIR':str(data),'KG3DR_EXPERIMENT_DIR':str(folder/'experiments'),
                     'KG3DR_OUTPUT_DIR':str(folder/'outputs'),'KG3DR_PROJECT':'kg3dr-ui-delete-'+uuid4().hex[:10]}
        with socket.socket() as socket_check:
            socket_check.bind(('127.0.0.1',0));port=socket_check.getsockname()[1]
        with (folder/'server.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1',
                                      '--port',str(port)],cwd=ROOT,env=environment,stdout=log,stderr=log)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(60):
                try:
                    opener.open(f'http://127.0.0.1:{port}/api/health',timeout=1).close();break
                except Exception:time.sleep(.2)
            executables=list(Path('/root/.cache/ms-playwright').glob('chromium_headless_shell*/**/chrome-headless-shell'))
            if not executables:raise ValueError('未找到测试浏览器')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=str(executables[0]),args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1400,'height':900})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{port}/#papers',wait_until='networkidle')
                button=page.locator('[data-delete-paper="P001"]')
                expect(button).to_be_visible()
                cancel=lambda dialog:dialog.dismiss()
                page.on('dialog',cancel);button.click()
                assert pdf.exists()
                page.remove_listener('dialog',cancel)
                page.on('dialog',lambda dialog:dialog.accept());button.click()
                expect(button).to_have_count(0,timeout=20000)
                assert not pdf.exists()
                assert json.loads((data/'papers.json').read_text())==[]
                manifests=list((data/'deleted').glob('*/manifest.json'))
                assert len(manifests)==1
                assert json.loads(manifests[0].read_text())['status']=='complete'
                assert not errors,errors
                browser.close()
            print('删除按钮测试通过：取消不修改数据，确认后清理记录并生成备份，无JS异常。测试语料已隔离清理。')
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':check()
