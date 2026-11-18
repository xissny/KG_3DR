import io
import pymupdf as fitz
from fastapi.testclient import TestClient
from backend.app import app
from src.common.storage import read_json


def test_upload_rejects_non_pdf_and_sanitizes_names(workspace):
    with TestClient(app) as client:
        response=client.post('/api/upload',files=[('files',('evil.txt',b'not pdf','text/plain'))])
        assert response.status_code==200
        assert response.json()['failures']
        document=fitz.open();page=document.new_page();page.insert_text((60,60),'Synthetic upload test document, not research data.')
        content=document.tobytes();document.close()
        response=client.post('/api/upload',files=[('files',('../../escape.pdf',content,'application/pdf'))])
        assert response.json()['stored']==['escape.pdf']
        assert (workspace[0]/'pdfs/escape.pdf').exists()
        assert not (workspace[0].parent/'escape.pdf').exists()


def test_health_does_not_expose_secrets(workspace):
    with TestClient(app) as client:
        value=client.get('/api/health').json()
        assert 'deepseek_configured' in value
        assert 'DEEPSEEK_API_KEY' not in value and 'password' not in value
        assert client.get('/').status_code==200


def test_output_download_cannot_read_env(workspace):
    with TestClient(app) as client:
        response=client.get('/api/download/%2e%2e/.env')
        assert response.status_code==404


def test_job_recovery_marks_running_interrupted(workspace):
    from backend.jobs import recover_jobs
    from src.common.storage import write_json
    path=workspace[0]/'jobs/test.json'
    write_json(path,{'id':'test','kind':'parse','status':'running','created_at':'2026-01-01'})
    recover_jobs()
    assert read_json(path)['status']=='interrupted'


def test_web_button_dispatch_runs_real_classification_module(workspace):
    import time
    with TestClient(app) as client:
        response=client.post('/api/run',json={'stage':'classification'})
        assert response.status_code==200
        job_id=response.json()['id']
        for _ in range(100):
            job=next(row for row in client.get('/api/jobs').json() if row['id']==job_id)
            if job['status'] in ['complete','failed']:break
            time.sleep(.03)
        assert job['status']=='complete',job
        assert job['result']['status']=='complete'
        state=client.get('/api/state').json()
        assert state['results']['classification']['leakage_check']['text_not_used']
