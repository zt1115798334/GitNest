import json
import threading
import time
from types import SimpleNamespace

from gitnest import database, services


def test_download_all_uses_bounded_workers_and_preserves_input_order(tmp_path, monkeypatch):
    lock = threading.Lock()
    active = 0
    peak = 0

    def fake_download(_repository, _token, remote_path, _root, _conflict):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return tmp_path / remote_path.rsplit("/", 1)[-1]

    monkeypatch.setattr(services, "download_one", fake_download)
    items = [SimpleNamespace(path=f"images/{index}.png") for index in range(8)]

    results = services.download_all(
        {}, "token", str(tmp_path), items, max_workers=3
    )

    assert [row[0] for row in results] == [item.path for item in items]
    assert all(row[1] == "downloaded" for row in results)
    assert 2 <= peak <= 3


def test_get_upload_task_finds_old_tasks_beyond_recent_list_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "tasks.sqlite3")
    database.initialize()
    repository = database.save_repository({
        "name": "Test repository", "platform": "github", "owner": "owner",
        "repo": "repo", "branch": "main", "base_path": "images",
    })
    first_id = database.create_upload_task(repository["id"], {"marker": "oldest"})

    with database.connection() as db:
        db.executemany(
            "INSERT INTO upload_tasks(repository_id,payload_json,status,summary) VALUES(?,?,'queued','queued')",
            [(repository["id"], json.dumps({"index": index})) for index in range(520)],
        )

    task = database.get_upload_task(first_id)

    assert task is not None
    assert task["payload"] == {"marker": "oldest"}
