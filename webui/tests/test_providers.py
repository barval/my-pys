import json

import pytest

from webui.providers import (
    Provider, delete_provider, fetch_models, load_providers, save_providers, slugify, upsert_provider,
)


def route(base_url, model):
    return {"name": "speaker-a", "primary": {"base_url": base_url, "model": model, "api_key_file": "k"}}


def test_registry_is_built_from_routes_without_duplicates(tmp_path):
    path = tmp_path / "providers.json"
    providers = load_providers(path, [
        route("http://10.0.0.2:5000/v1", "model-a"),
        route("http://10.0.0.2:5000/v1", "model-b"),
        route("http://10.0.0.3:5000/v1", "model-c"),
    ])
    assert len(providers) == 2
    assert [p.models for p in providers if p.base_url.endswith("10.0.0.2:5000/v1")] == [("model-a", "model-b")]
    assert json.loads(path.read_text(encoding="utf-8"))["providers"][0]["base_url"]


def test_upsert_and_delete(tmp_path):
    path = tmp_path / "providers.json"
    save_providers(path, [])
    upsert_provider(path, Provider("flai", "FLAI", "http://10.0.0.2:5000/v1", ("m",)))
    upsert_provider(path, Provider("flai", "FLAI 2", "http://10.0.0.2:5000/v2", ("m2",)))
    providers = load_providers(path, [])
    assert len(providers) == 1 and providers[0].name == "FLAI 2"


def test_slugify():
    assert slugify("My Provider!") == "my-provider"
    assert slugify("  ") == "provider"


def test_fetch_models_parses_openai_response():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"data":[{"id":"model-a"},{"id":"model-b"}]}'

    assert fetch_models("http://10.0.0.2:5000/v1", "secret", opener=lambda *a, **k: Response()) == ["model-a", "model-b"]


def test_delete_provider(tmp_path):
    path = tmp_path / "providers.json"
    save_providers(path, [Provider("a", "A", "http://10.0.0.2:5000/v1", ("m",))])
    delete_provider(path, "a")
    assert load_providers(path, []) == []
    with pytest.raises(KeyError):
        delete_provider(path, "a")
