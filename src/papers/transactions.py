"""论文数据变更的事务边界：完整备份、数据库提交、文件写入及失败回滚。"""
from pathlib import Path
import shutil
from src.common.storage import write_json
from src.graph import store


def commit_changes(changes: dict[Path, bytes | None], backup: Path, manifest: dict,
                   old_live: dict | None = None, new_live: dict | None = None) -> bool:
    """changes中None表示删除；所有目标内容预先准备，避免文件改名覆盖其他论文。"""
    backup.mkdir(parents=True, exist_ok=True)
    manifest.update(status='preparing', files=[])
    for index, path in enumerate(changes):
        existed = path.exists()
        saved = backup / 'files' / str(index)
        if existed:
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
        manifest['files'].append({'path': str(path), 'backup': str(saved), 'existed': existed})
    write_json(backup / 'manifest.json', manifest)
    database_updated = False
    try:
        if new_live is not None:
            with store.driver() as connection, connection.session() as session:
                session.execute_write(store._replace_graph, new_live)
            database_updated = True
        for path, content in changes.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + '.delete-tmp')
                temporary.write_bytes(content)
                temporary.replace(path)
        manifest['status'] = 'complete'
        write_json(backup / 'manifest.json', manifest)
    except Exception:
        for path in changes:
            path.with_name(path.name + '.delete-tmp').unlink(missing_ok=True)
        for record in manifest['files']:
            path = Path(record['path'])
            if record['existed']:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(record['backup'], path)
            else:
                path.unlink(missing_ok=True)
        if database_updated:
            with store.driver() as connection, connection.session() as session:
                session.execute_write(store._replace_graph, old_live)
        manifest['status'] = 'rolled_back'
        write_json(backup / 'manifest.json', manifest)
        raise
    return database_updated
