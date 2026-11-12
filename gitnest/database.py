import sqlite3
from contextlib import contextmanager
from gitnest.config import DB_PATH

@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def initialize() -> None:
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, platform TEXT NOT NULL CHECK(platform IN ('github','gitee')),
            owner TEXT NOT NULL, repo TEXT NOT NULL, branch TEXT NOT NULL,
            base_path TEXT NOT NULL DEFAULT 'images', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(platform, owner, repo, branch, base_path))""")
        db.execute("""CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, repository_id INTEGER,
            action TEXT NOT NULL, file_path TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE SET NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS upload_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(repository_id) REFERENCES repositories(id) ON DELETE SET NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_upload_tasks_status_updated ON upload_tasks(status, updated_at DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_operation_logs_created ON operation_logs(id DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        db.execute("UPDATE upload_tasks SET status='paused', summary='程序上次未正常结束，可继续或取消' WHERE status='running'")

def repositories() -> list[dict]:
    with connection() as db:
        return [dict(r) for r in db.execute("SELECT * FROM repositories ORDER BY name COLLATE NOCASE")]

def save_repository(data: dict) -> dict:
    with connection() as db:
        db.execute("""INSERT INTO repositories(name,platform,owner,repo,branch,base_path)
            VALUES(:name,:platform,:owner,:repo,:branch,:base_path)
            ON CONFLICT(platform,owner,repo,branch,base_path) DO UPDATE SET name=excluded.name""", data)
        row = db.execute("""SELECT * FROM repositories WHERE platform=? AND owner=? AND repo=?
            AND branch=? AND base_path=?""", (data['platform'],data['owner'],data['repo'],data['branch'],data['base_path'])).fetchone()
        return dict(row)

def delete_repository(repository_id: int) -> None:
    with connection() as db:
        db.execute("DELETE FROM repositories WHERE id=?", (repository_id,))

def add_log(repository_id: int | None, action: str, path: str, status: str, message: str) -> None:
    with connection() as db:
        db.execute("INSERT INTO operation_logs(repository_id,action,file_path,status,message) VALUES(?,?,?,?,?)",
                   (repository_id, action, path, status, message[:1500]))

def logs(limit: int = 300) -> list[dict]:
    with connection() as db:
        return [dict(r) for r in db.execute("""SELECT l.*,r.name AS repository_name FROM operation_logs l
            LEFT JOIN repositories r ON r.id=l.repository_id ORDER BY l.id DESC LIMIT ?""", (limit,))]


def create_upload_task(repository_id: int, payload: dict) -> int:
    import json
    with connection() as db:
        cur=db.execute("INSERT INTO upload_tasks(repository_id,payload_json,status,summary) VALUES(?,?,'queued','等待上传')",
                       (repository_id,json.dumps(payload,ensure_ascii=False)))
        return int(cur.lastrowid)

def update_upload_task(task_id: int, *, payload: dict | None = None,
                       status: str | None = None, summary: str | None = None) -> None:
    import json
    fields=[]
    values=[]
    if payload is not None:
        fields.append("payload_json=?");values.append(json.dumps(payload,ensure_ascii=False))
    if status is not None:
        fields.append("status=?");values.append(status)
    if summary is not None:
        fields.append("summary=?");values.append(summary[:1500])
    if not fields:return
    fields.append("updated_at=CURRENT_TIMESTAMP")
    values.append(task_id)
    with connection() as db:
        db.execute(f"UPDATE upload_tasks SET {', '.join(fields)} WHERE id=?",values)

def upload_task_rows(limit: int = 100) -> list[dict]:
    import json
    with connection() as db:
        rows=db.execute("SELECT * FROM upload_tasks ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        try:item["payload"]=json.loads(item.pop("payload_json"))
        except (ValueError,TypeError):item["payload"]={}
        result.append(item)
    return result

def get_upload_task(task_id: int) -> dict | None:
    import json
    with connection() as db:
        row = db.execute("SELECT * FROM upload_tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    try:
        item["payload"] = json.loads(item.pop("payload_json"))
    except (ValueError, TypeError):
        item["payload"] = {}
    return item



def get_settings() -> dict:
    with connection() as db:
        rows = db.execute("SELECT key, value FROM app_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_setting(key: str, value: str) -> None:
    with connection() as db:
        db.execute(
            "INSERT INTO app_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
