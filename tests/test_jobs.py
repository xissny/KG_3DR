"""运行记录清理：只删除终态元数据和输出副本，不触碰业务产物。"""
from threading import Event
import time
from fastapi.testclient import TestClient
from backend.app import app
from backend import jobs
from src.common.storage import read_json, write_json


def add_job(data, job_id, status):
    row={'id':job_id,'kind':'parse','status':status,'created_at':'2026-11-11T00:00:00+00:00',
         'result':{'example':job_id} if status=='complete' else None}
    write_json(data/'jobs'/f'{job_id}.json',row)
    write_json(data/'jobs'/f'{job_id}.result.json',{'example':job_id})


def test_clear_history_preserves_active_jobs_and_research_files(workspace):
    data,exp=workspace
    for job_id,status in [('done','complete'),('error','failed'),('stopped','interrupted'),
                           ('active','running'),('waiting','queued'),('unknown','custom')]:
        add_job(data,job_id,status)
    write_json(exp/'classification.json',{'keep':'experiment'})
    write_json(data/'cache/keep.json',{'keep':'api-cache'})
    write_json(data/'graph_snapshot.json',{'keep':'graph'})
    protected={p:p.read_bytes() for p in [exp/'classification.json',data/'cache/keep.json',
                                        data/'graph_snapshot.json',data/'papers.json',data/'candidates/P001.json']}
    result=jobs.clear_finished_jobs()
    assert result['cleared']==3 and result['kept_active']==2
    for job_id in ['done','error','stopped']:
        assert not (data/'jobs'/f'{job_id}.json').exists()
        assert not (data/'jobs'/f'{job_id}.result.json').exists()
    for job_id in ['active','waiting','unknown']:
        assert (data/'jobs'/f'{job_id}.json').exists()
        assert (data/'jobs'/f'{job_id}.result.json').exists()
    assert all(path.read_bytes()==content for path,content in protected.items())
    assert jobs.clear_finished_jobs()['cleared']==0


def test_delete_jobs_endpoint_clears_all_history_not_just_recent_30(workspace):
    data,_=workspace
    with TestClient(app) as client:
        for index in range(42):add_job(data,f'finished-{index:02}','complete')
        add_job(data,'running','running')
        add_job(data,'queued','queued')
        assert len(client.get('/api/jobs').json())==30
        response=client.delete('/api/jobs')
        assert response.status_code==200
        assert response.json()['cleared']==42
        assert response.json()['kept_active']==2
        assert {row['id'] for row in client.get('/api/jobs').json()}=={'running','queued'}
        assert client.delete('/api/jobs').json()['cleared']==0


def test_active_job_can_finish_normally_after_clearing_history(workspace):
    data,_=workspace
    started,release=Event(),Event()
    def task():
        started.set()
        assert release.wait(5),'test task was not released'
        return {'finished_after_clear':True}
    add_job(data,'old','complete')
    job=jobs.submit_job('test',task,{})
    try:
        assert started.wait(2)
        result=jobs.clear_finished_jobs()
        assert result['cleared']==1 and result['kept_active']==1
        assert (data/'jobs'/f"{job['id']}.json").exists()
    finally:release.set()
    for _ in range(100):
        finished=read_json(data/'jobs'/f"{job['id']}.json",{})
        if finished.get('status') in ('complete','failed'):break
        time.sleep(.02)
    assert finished['status']=='complete'
    assert finished['result']=={'finished_after_clear':True}
    assert (data/'jobs'/f"{job['id']}.result.json").exists()
    assert jobs.clear_finished_jobs()['cleared']==1


def test_poll_tolerates_history_removed_during_directory_scan(workspace,monkeypatch):
    data,_=workspace
    add_job(data,'gone','complete')
    add_job(data,'kept','running')
    original=jobs.read_json
    def concurrent_read(path,default=None):
        if path.name=='gone.json':raise FileNotFoundError('cleared during polling')
        return original(path,default)
    monkeypatch.setattr(jobs,'read_json',concurrent_read)
    assert [job['id'] for job in jobs.list_jobs()]==['kept']
