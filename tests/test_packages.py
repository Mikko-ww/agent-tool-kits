import pytest

from atkits.packages import PackageError, sha256_file


def test_package_rejects_path_traversal(package_store, malicious_archive):
    with pytest.raises(PackageError, match="unsafe path"):
        package_store.extract(malicious_archive, "skill", "foo", "1.0.0")


def test_package_hash_mismatch_does_not_create_package(
    package_store, asset, write_corrupted_archive
):
    with pytest.raises(PackageError, match="sha256"):
        package_store.ensure(asset, downloader=write_corrupted_archive)
    assert not package_store.path_for("skill", "foo", "1.1.0").exists()


def test_existing_non_empty_package_dir_is_not_replaced(package_store, asset, write_valid_archive):
    package_store.ensure(asset, downloader=write_valid_archive)
    target = package_store.path_for("skill", "foo", "1.1.0")
    target.rename(target.with_suffix(".keep"))
    target.mkdir()
    (target / "unexpected.txt").write_text("x")
    with pytest.raises(PackageError, match="already exists"):
        package_store.ensure(asset, downloader=write_valid_archive)


def test_ensure_extracts_valid_package(package_store, asset, write_valid_archive):
    result = package_store.ensure(asset, downloader=write_valid_archive)
    assert result == package_store.path_for("skill", "foo", "1.1.0")
    assert (result / "SKILL.md").is_file()


def test_second_identical_version_uses_cache(package_store, asset, write_valid_archive):
    first = package_store.ensure(asset, downloader=write_valid_archive)
    second = package_store.ensure(asset, downloader=write_valid_archive)
    assert first == second


def test_package_rejects_symlink_entries(package_store, symlink_archive):
    with pytest.raises(PackageError, match="unsafe entry"):
        package_store.extract(symlink_archive, "skill", "foo", "1.0.0")


def test_package_rejects_wrong_name_or_version(package_store, wrong_version_archive, wrong_asset):
    with pytest.raises(PackageError, match="version"):
        package_store.extract(wrong_version_archive, "skill", "foo", "9.9.9")


def test_sha256_file_is_stable(tmp_path):
    path = tmp_path / "file.txt"
    path.write_bytes(b"stable")
    assert sha256_file(path) == sha256_file(path)
