from gitnest import database


def test_desktop_preferences_persist_and_update(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "preferences.sqlite3")
    database.initialize()

    database.set_setting("download_folder", str(tmp_path / "downloads"))
    database.set_setting("download_workers", "6")
    database.set_setting("download_workers", "4")

    values = database.get_settings()
    assert values["download_folder"] == str(tmp_path / "downloads")
    assert values["download_workers"] == "4"


def test_preferences_are_empty_on_first_start(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "fresh.sqlite3")
    database.initialize()
    assert database.get_settings() == {}
