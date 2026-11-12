import threading

from gitnest import database
from gitnest.services import UploadControl


def test_upload_task_payload_persists_and_can_be_retrieved(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "gitnest.sqlite3")
    database.initialize()

    payload = {
        "paths": ["C:/photos/a.png", "C:/photos/b.png"],
        "relative_to": "C:/photos",
        "conflict": "skip",
        "completed": {
            "C:/photos/a.png": {"state": "uploaded", "message": "已上传"}
        },
    }
    task_id = database.create_upload_task(1, payload)
    database.update_upload_task(
        task_id,
        payload={**payload, "completed": {
            **payload["completed"],
            "C:/photos/b.png": {"state": "failed", "message": "网络错误"},
        }},
        status="failed",
        summary="1 项成功，1 项失败",
    )

    task = database.get_upload_task(task_id)

    assert task is not None
    assert task["repository_id"] == 1
    assert task["status"] == "failed"
    assert task["summary"] == "1 项成功，1 项失败"
    assert task["payload"]["completed"]["C:/photos/a.png"]["state"] == "uploaded"
    assert task["payload"]["completed"]["C:/photos/b.png"]["state"] == "failed"


def test_initialize_recovers_interrupted_running_tasks_as_paused(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "gitnest.sqlite3")
    database.initialize()
    task_id = database.create_upload_task(1, {"paths": ["photo.png"]})
    database.update_upload_task(task_id, status="running", summary="正在上传")

    # A second initialization represents the next application startup.
    database.initialize()

    task = database.get_upload_task(task_id)
    assert task["status"] == "paused"
    assert "未正常结束" in task["summary"]


def test_upload_control_pause_blocks_until_resume():
    control = UploadControl()
    control.pause()
    started = threading.Event()
    finished = threading.Event()
    result = []

    def wait_at_checkpoint():
        started.set()
        result.append(control.checkpoint())
        finished.set()

    worker = threading.Thread(target=wait_at_checkpoint)
    worker.start()
    assert started.wait(1)
    assert not finished.wait(0.05)

    control.resume()
    worker.join(timeout=1)

    assert finished.is_set()
    assert result == [True]


def test_upload_control_cancel_releases_paused_checkpoint():
    control = UploadControl()
    control.pause()
    started = threading.Event()
    result = []

    def wait_at_checkpoint():
        started.set()
        result.append(control.checkpoint())

    worker = threading.Thread(target=wait_at_checkpoint)
    worker.start()
    assert started.wait(1)

    control.cancel()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == [False]
