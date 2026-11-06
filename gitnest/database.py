import sqlite3
from contextlib import contextmanager
from gitnest.config import DB_PATH

@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def initialize() -> None:
    with connection() as db:
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
