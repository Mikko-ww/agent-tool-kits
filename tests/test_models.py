import pytest

from atkits.models import AssetVersion, Catalog, RegistryError


def test_latest_ignores_prerelease_and_upload_order(catalog):
    assert catalog.latest("skill", "foo").version == "1.1.0"
    assert catalog.latest("skill", "foo").asset_id == 10002


def test_semver_build_metadata_does_not_change_precedence():
    with pytest.raises(RegistryError, match="same precedence"):
        Catalog(
            {
                "schema_version": 1,
                "skills": {
                    "foo": {
                        "latest": "1.1.0",
                        "versions": {
                            "1.1.0": {"asset_id": 1, "archive": "a", "sha256": "0" * 64},
                            "1.1.0+build.1": {
                                "asset_id": 2,
                                "archive": "b",
                                "sha256": "1" * 64,
                            },
                        },
                    }
                },
            }
        )


def test_catalog_allows_different_prerelease_versions():
    catalog = Catalog(
        {
            "schema_version": 1,
            "skills": {
                "foo": {
                    "latest": "1.0.0-beta.2",
                    "versions": {
                        "1.0.0-alpha": {
                            "asset_id": 1,
                            "archive": "a",
                            "sha256": "0" * 64,
                        },
                        "1.0.0-beta": {
                            "asset_id": 2,
                            "archive": "b",
                            "sha256": "1" * 64,
                        },
                    },
                }
            },
        }
    )
    assert set(catalog.require_version("skill", "foo", "1.0.0-alpha").version for _ in [None]) == {
        "1.0.0-alpha"
    }


def test_install_target_key_is_stable(install_target):
    assert install_target.key() == "skill:foo:global:agents"


def test_catalog_rejects_unknown_schema_version():
    with pytest.raises(RegistryError, match="schema_version"):
        Catalog({"schema_version": 999, "skills": {}})


def test_catalog_rejects_invalid_sha256():
    with pytest.raises(RegistryError, match="sha256"):
        Catalog(
            {
                "schema_version": 1,
                "skills": {
                    "foo": {
                        "latest": "1.0.0",
                        "versions": {
                            "1.0.0": {
                                "asset_id": 1,
                                "archive": "foo.tar.gz",
                                "sha256": "not-a-hash",
                            }
                        },
                    }
                },
            }
        )


def test_catalog_rejects_empty_name():
    with pytest.raises(RegistryError, match="name"):
        Catalog(
            {
                "schema_version": 1,
                "skills": {
                    "": {
                        "latest": "1.0.0",
                        "versions": {
                            "1.0.0": {
                                "asset_id": 1,
                                "archive": "foo.tar.gz",
                                "sha256": "0" * 64,
                            }
                        },
                    }
                },
            }
        )


def test_catalog_rejects_duplicate_version_entries():
    with pytest.raises(RegistryError, match="duplicate"):
        Catalog(
            {
                "schema_version": 1,
                "skills": {
                    "foo": {
                        "latest": "1.0.0",
                        "versions": {
                            "1.0.0": {
                                "asset_id": 1,
                                "archive": "foo.tar.gz",
                                "sha256": "0" * 64,
                            },
                            "1.0.0+build.1": {
                                "asset_id": 2,
                                "archive": "foo.tar.gz",
                                "sha256": "1" * 64,
                            },
                        },
                    }
                },
            }
        )


def test_require_version_returns_exact_asset(catalog):
    asset = catalog.require_version("skill", "foo", "1.0.0")
    assert asset == AssetVersion(
        kind="skill",
        name="foo",
        version="1.0.0",
        asset_id=10001,
        archive="foo-1.0.0.tar.gz",
        sha256="0" * 64,
    )


def test_require_version_rejects_missing_version(catalog):
    with pytest.raises(RegistryError, match="foo@9.9.9"):
        catalog.require_version("skill", "foo", "9.9.9")


def test_catalog_rejects_missing_asset_id():
    with pytest.raises(RegistryError, match="asset_id"):
        Catalog(
            {
                "schema_version": 1,
                "skills": {
                    "foo": {
                        "versions": {
                            "1.0.0": {
                                "archive": "foo.tar.gz",
                                "sha256": "0" * 64,
                            }
                        },
                    }
                },
            }
        )


def test_catalog_rejects_non_string_archive():
    with pytest.raises(RegistryError, match="archive"):
        Catalog(
            {
                "schema_version": 1,
                "skills": {
                    "foo": {
                        "versions": {
                            "1.0.0": {
                                "asset_id": 1,
                                "archive": 123,
                                "sha256": "0" * 64,
                            }
                        },
                    }
                },
            }
        )


def test_asset_version_rejects_non_string_description():
    with pytest.raises(RegistryError, match="description"):
        AssetVersion(
            kind="skill",
            name="foo",
            version="1.0.0",
            asset_id=1,
            archive="foo.tar.gz",
            sha256="0" * 64,
            description=123,
        )


def test_catalog_names_returns_sorted_asset_names(catalog):
    assert catalog.names("skill") == ["foo"]


def test_catalog_exposes_external_skills_and_presets():
    catalog = Catalog(
        {
            "schema_version": 1,
            "skills": {},
            "external_skills": {
                "pdf": {"source": "openai/skills"},
            },
            "collection": {
                "presets": {
                    "daily-coding": {
                        "scope": "global",
                        "platforms": ["codex", "cursor"],
                        "method": "symlink",
                    }
                }
            },
        }
    )
    assert catalog.external_skills() == {"pdf": {"source": "openai/skills"}}
    preset = catalog.preset("daily-coding")
    assert preset.scope == "global"
    assert preset.platforms == ("codex", "cursor")
    assert preset.method == "symlink"


def test_catalog_parses_direct_cli_section():
    catalog = Catalog(
        {
            "schema_version": 1,
            "cli": {
                "latest": "0.2.0",
                "versions": {
                    "0.2.0": {
                        "asset_id": 1,
                        "archive": "atkits-0.2.0-py3-none-any.whl",
                        "sha256": "0" * 64,
                    }
                },
            },
        }
    )
    assert catalog.names("cli") == ["atkits"]
    assert catalog.latest("cli", "atkits").version == "0.2.0"
