"""Small provider parity demonstration; run with `python source/test_data/demo_media_discovery.py`."""

from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from media.media_discovery import discover_media  # noqa: E402
from media.json_provider import InventoryFormatError, discover_json  # noqa: E402


def main() -> None:
    json_inventory = discover_media({"discovery_mode": "json"})
    categories = json_inventory["categories"]
    movies = categories["movies"]["folders"]
    assert len(movies) == 6
    assert [movie["folder_id"] for movie in movies] == ["movie1", "movie2", "movie3", "movie4", "movie5", "movie6"]
    assert len(categories["ads"]["files"]) == 3
    assert len(categories["dev-songs"]["files"]) == 6
    assert len(categories["movie-songs"]["files"]) == 3
    assert len(categories["songs"]["files"]) == 6
    assert all(movie["files"][0]["duration_seconds"] for movie in movies)
    assert all(song["duration_seconds"] for name in ("ads", "dev-songs", "movie-songs", "songs")
               for song in categories[name]["files"])

    # Exercise the filesystem provider in isolation with temporary placeholder
    # files. Discovery records names and paths; it does not inspect media bytes.
    with TemporaryDirectory() as temporary:
        media_root = Path(temporary)
        for category in ("movies", "dev-songs", "movie-songs", "songs", "ads"):
            (media_root / category).mkdir()
        for folder_id in ("m1", "m2", "m10"):
            folder = media_root / "movies" / folder_id
            folder.mkdir()
            (folder / (folder_id + ".mp4")).touch()
        (media_root / "ads" / "sample-ad.mp4").touch()
        filesystem_inventory = discover_media({
            "discovery_mode": "filesystem",
            "media_root": str(media_root),
        })
        (media_root / "inventory.json").write_text(json.dumps({
            "movies": {"exists": False, "folders": []},
            "dev-songs": {"exists": True, "files": []},
            "movie-songs": {"exists": True, "files": []},
        }), encoding="utf-8")
        sparse_json = discover_json(media_root / "inventory.json")
        assert sparse_json["categories"]["movies"]["exists"] is False
        assert sparse_json["categories"]["dev-songs"]["exists"] is True
        assert sparse_json["categories"]["movie-songs"]["exists"] is True
        assert sparse_json["categories"]["songs"]["exists"] is False
        (media_root / "bad.json").write_text('{broken', encoding="utf-8")
        try:
            discover_json(media_root / "bad.json")
        except InventoryFormatError:
            pass
        else:
            raise AssertionError("Malformed inventory JSON should raise InventoryFormatError")

    with TemporaryDirectory() as temporary:
        missing_root_inventory = discover_media({
            "discovery_mode": "filesystem",
            "media_root": str(Path(temporary) / "not-created"),
        })
        assert missing_root_inventory["categories"]["movies"]["exists"] is False
        assert missing_root_inventory["categories"]["ads"]["exists"] is False

    # Both modes use the same top-level/category/file/folder field contract.
    assert set(json_inventory) == set(filesystem_inventory)
    assert set(json_inventory["categories"]) == set(filesystem_inventory["categories"])
    assert set(json_inventory["categories"]["movies"]) == set(filesystem_inventory["categories"]["movies"])
    assert set(json_inventory["categories"]["songs"]) == set(filesystem_inventory["categories"]["songs"])
    assert set(json_inventory["categories"]["movie-songs"]) == set(filesystem_inventory["categories"]["movie-songs"])
    assert [folder["folder_id"] for folder in filesystem_inventory["categories"]["movies"]["folders"]] == ["m1", "m2", "m10"]
    assert filesystem_inventory["categories"]["dev-songs"]["exists"] is True
    assert filesystem_inventory["categories"]["dev-songs"]["files"] == []
    assert filesystem_inventory["categories"]["songs"]["exists"] is True
    assert filesystem_inventory["categories"]["movie-songs"]["exists"] is True

    print("JSON inventory: 6 movies, 3 ads, 6 devotional songs, 3 movie songs, 6 regular songs")
    print("Movie folder IDs preserved; durations present; provider structures compatible")
    print("Filesystem provider independently discovered temporary directory contents")


if __name__ == "__main__":
    main()
