"""Keep fresh deployment recommendations and instance engine settings in agreement."""

import runpy
from pathlib import Path

import yaml

from bensz_search.searxng import DEFAULT_ENGINES


def test_deployment_defaults_enable_every_recommended_engine(tmp_path, monkeypatch):
    monkeypatch.delenv("SEARXNG_ENGINES", raising=False)
    deploy = Path("docs/deploy")
    initialize = runpy.run_path(str(deploy / "deploy_local.py"))["initialize"]
    settings = yaml.safe_load((deploy / "searxng-settings.yml.example").read_text())
    expected = ",".join(DEFAULT_ENGINES)
    values = initialize(tmp_path)
    assert values["SEARXNG_ENGINES"] == expected
    env = dict(
        line.split("=", 1)
        for line in (deploy / ".env.example").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert env["SEARXNG_ENGINES"] == expected
    assert [engine["name"] for engine in settings["engines"] if not engine["disabled"]] == list(
        DEFAULT_ENGINES
    )
    assert "json" in settings["search"]["formats"]
    # A new environment must not overwrite an existing deployment's chosen engines or secrets.
    before = (tmp_path / ".env").read_bytes()
    monkeypatch.setenv("SEARXNG_ENGINES", "pubmed")
    assert initialize(tmp_path)["SEARXNG_ENGINES"] == expected
    assert (tmp_path / ".env").read_bytes() == before
