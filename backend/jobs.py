"""单进程后台任务队列：序列化写操作，刷新网页不丢状态。"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import uuid
from src.common.storage import DATA, now, read_json, write_json

EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kg-stage')
LOCK = Lock()


def recover_jobs():
    for path in (DATA / 'jobs').glob('*.json'):
        if path.name.endswith('.result.json'):
            continue
        job = read_json(path)
        if job['status'] in ('running', 'queued'):
            job.update(status='interrupted', error='服务重启，重新提交可复用已完成缓存', finished_at=now())
            write_json(path, job)


def list_jobs():
    rows = []
    for path in (DATA / 'jobs').glob('*.json'):
        if path.name.endswith('.result.json'):
            continue
        try:
            job = read_json(path)
        except FileNotFoundError:
            # 清理记录可能与浏览器轮询同时发生，跳过刚被删除的文件。
            continue
        if job is not None:
            rows.append(job)
    return sorted(rows, key=lambda job: job['created_at'], reverse=True)[:30]


def clear_finished_jobs() -> dict:
    """只清理终态运行记录及其输出副本；实验产物和活跃任务不在清理范围。

    扫描全部记录而非list_jobs的最近30条。与任务提交共用锁；正在执行的
    任务即使在清理期间完成，也会保留其原记录，下一次清理时再处理。
    """
    cleared = 0
    kept_active = 0
    with LOCK:
        for path in sorted((DATA / 'jobs').glob('*.json')):
            if path.name.endswith('.result.json'):
                continue
            job = read_json(path, {})
            if job.get('status') in ('queued', 'running'):
                kept_active += 1
                continue
            if job.get('status') not in ('complete', 'failed', 'interrupted'):
                continue
            # 路径取自当前目录中的文件名，不采用记录内的ID拼接任意路径。
            path.with_name(path.stem + '.result.json').unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            cleared += 1
    return {'cleared': cleared, 'kept_active': kept_active,
            'note': '仅清除已结束运行记录；论文、审核、图谱、API缓存和实验结果保持不变。'}


def submit_job(kind: str, function, arguments: dict, with_progress=False):
    with LOCK:
        if any(j['status'] in ('queued', 'running') for j in list_jobs()):
            raise ValueError('已有阶段任务正在运行，请等待完成后再启动')
        job_id = uuid.uuid4().hex
        path = DATA / 'jobs' / f'{job_id}.json'
        job = {'id': job_id, 'kind': kind, 'arguments': arguments, 'status': 'queued',
               'created_at': now(), 'logs': [], 'completed': 0, 'total': None}
        write_json(path, job)
        def run():
            def progress(message, completed=0, total=None):
                job.update(completed=completed, total=total)
                job['logs'] = (job['logs'] + [{'time': now(), 'message': message}])[-100:]
                write_json(path, job)
            try:
                job.update(status='running', started_at=now())
                write_json(path, job)
                kwargs = dict(arguments)
                if with_progress:
                    kwargs['progress'] = progress
                result = function(**kwargs)
                result_path = DATA / 'jobs' / f'{job_id}.result.json'
                write_json(result_path, result)
                job.update(status='complete', result=result, finished_at=now())
            except Exception as exc:
                job.update(status='failed', error=str(exc), finished_at=now())
            write_json(path, job)
        EXECUTOR.submit(run)
    return job
