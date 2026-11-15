"""Folders after the SkySqueezer rename: sks-dl, unless an install from before it has only edh-dl."""

from skysqueezer import paths


def _xdg(monkeypatch, tmp_path):
    for var in ("SKS_DL_CONFIG_DIR", "EDH_DL_CONFIG_DIR", "SKS_DL_DATA_DIR", "EDH_DL_DATA_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))


def test_a_new_install_uses_sks_dl(tmp_path, monkeypatch):
    _xdg(monkeypatch, tmp_path)
    assert paths.config_dir() == tmp_path / "config" / "sks-dl"
    assert paths.jobs_dir() == tmp_path / "share" / "sks-dl" / "jobs"
    assert not (tmp_path / "config" / "edh-dl").exists()


def test_an_old_install_keeps_its_edh_dl_folders(tmp_path, monkeypatch):
    _xdg(monkeypatch, tmp_path)
    old = tmp_path / "config" / "edh-dl"
    old.mkdir(parents=True)
    (old / "keys.json").write_text("{}")
    assert paths.config_dir() == old  # the keys are found; nothing moved
    assert not (tmp_path / "config" / "sks-dl").exists()


def test_once_sks_dl_exists_it_wins(tmp_path, monkeypatch):
    _xdg(monkeypatch, tmp_path)
    (tmp_path / "share" / "edh-dl").mkdir(parents=True)
    (tmp_path / "share" / "sks-dl").mkdir(parents=True)
    assert paths.data_dir() == tmp_path / "share" / "sks-dl"


def test_old_variable_names_still_work(tmp_path, monkeypatch):
    _xdg(monkeypatch, tmp_path)
    monkeypatch.setenv("EDH_DL_CONFIG_DIR", str(tmp_path / "old"))
    assert paths.config_dir() == tmp_path / "old"
    monkeypatch.setenv("SKS_DL_CONFIG_DIR", str(tmp_path / "new"))
    assert paths.config_dir() == tmp_path / "new"
    monkeypatch.setenv("EDH_DL_OFFLINE", "1")
    assert paths.env("OFFLINE") == "1"
