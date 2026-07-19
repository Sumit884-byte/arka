import io
import json
import zipfile
from pathlib import Path


def _archive_bytes() -> bytes:
    handle = io.BytesIO()
    with zipfile.ZipFile(handle, "w") as archive:
        archive.writestr("repo-main/data/items.csv", "id,name,kind\n1,Alpha,fruit\n2,Beta,veg\n")
        archive.writestr("repo-main/data/meta.json", json.dumps([{"id": 1, "name": "Alpha", "kind": "fruit"}]))
        archive.writestr("repo-main/node_modules/ignored.csv", "bad,data\n")
        archive.writestr("repo-main/README.md", "# ignored")
    return handle.getvalue()


def test_parse_repo_accepts_url_slug_and_branch():
    from arka.agent.github_dataset import parse_repo

    assert parse_repo("https://github.com/owner/data-repo").slug == "owner/data-repo"
    assert parse_repo("owner/data-repo").slug == "owner/data-repo"
    parsed = parse_repo("https://github.com/owner/data-repo/tree/dev")
    assert parsed.slug == "owner/data-repo"
    assert parsed.branch == "dev"


def test_import_repo_extracts_common_data_files(monkeypatch, tmp_path):
    from arka.agent import github_dataset as gd

    monkeypatch.setattr(gd, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(gd, "_download_bytes", lambda url, **kwargs: _archive_bytes())

    meta = gd.import_repo("owner/data-repo")

    assert meta["repo"] == "owner/data-repo"
    assert meta["file_count"] == 2
    paths = {item["path"] for item in meta["files"]}
    assert paths == {"data/items.csv", "data/meta.json"}
    csv_item = next(item for item in meta["files"] if item["path"] == "data/items.csv")
    assert csv_item["columns"] == ["id", "name", "kind"]
    assert Path(csv_item["cache_path"]).is_file()


def test_import_repo_prefers_github_contents_api(monkeypatch, tmp_path):
    from arka.agent import github_dataset as gd

    monkeypatch.setattr(gd, "cache_dir", lambda: tmp_path)

    def fake_download(url, **kwargs):
        if "api.github.com" in url and "/contents?" in url:
            return json.dumps(
                [
                    {"type": "dir", "path": "data"},
                    {"type": "file", "path": "package.json", "download_url": "https://raw/package.json", "size": 2},
                ]
            ).encode()
        if "api.github.com" in url and "/contents/data?" in url:
            return json.dumps(
                [
                    {
                        "type": "file",
                        "path": "data/items.csv",
                        "download_url": "https://raw/items.csv",
                        "size": 39,
                    }
                ]
            ).encode()
        if url == "https://raw/items.csv":
            return b"id,name,kind\n1,Alpha,fruit\n2,Beta,veg\n"
        raise AssertionError(f"unexpected download: {url}")

    monkeypatch.setattr(gd, "_download_bytes", fake_download)

    meta = gd.import_repo("owner/data-repo")

    assert meta["import_method"] == "github_contents_api"
    assert meta["file_count"] == 1
    assert meta["files"][0]["path"] == "data/items.csv"


def test_search_manifest_finds_cached_preview(monkeypatch, tmp_path):
    from arka.agent import github_dataset as gd

    monkeypatch.setattr(gd, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(gd, "_download_bytes", lambda url, **kwargs: _archive_bytes())
    gd.import_repo("owner/data-repo")

    rows = gd.search_manifest("owner/data-repo", "fruit", limit=5)

    assert [row["path"] for row in rows] == ["data/items.csv", "data/meta.json"]


def test_github_dataset_routes_general_repo_not_exercise_preset():
    from arka.routing.symbolic import route_offline_extras

    assert route_offline_extras("quickly add data from https://github.com/foo/bar") == "github_dataset import foo/bar"
    assert route_offline_extras("search github dataset foo/bar for ratings") == "github_dataset search foo/bar ratings"
    assert route_offline_extras("quickly add exercise data from hasaneyldrm/exercises-dataset") == "exercise_dataset import"


def test_cli_github_dataset_direct_command(monkeypatch, capsys, tmp_path):
    from arka import cli
    from arka.agent import github_dataset as gd

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr(gd, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(gd, "_download_bytes", lambda url, **kwargs: _archive_bytes())

    assert cli.main(["github-dataset", "import", "owner/data-repo", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"repo": "owner/data-repo"' in out
    assert '"file_count": 2' in out
