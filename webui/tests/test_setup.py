import json

from webui.providers import Provider, save_providers

from webui.tests.test_app import FakeRunner


def test_setup_page_lists_steps(client, login):
    login()
    body = client.get("/speakers/speaker-a/setup?step=7").get_data(as_text=True)
    assert "Quasar Bridge" in body
    assert "Маршрут и ключ" in body
    assert 'href="/setup/prepare"' in body
    assert "Подготовка хоста" in body
    assert 'aria-current="step"' in body
    assert 'class="breadcrumbs"' in body
    assert 'href="/speakers/speaker-a"' in body
    assert ">Настроить</span>" in body


def test_setup_step3_opens_scan_page_without_wait(client, login):
    login()
    body = client.get("/speakers/speaker-a/setup?step=3").get_data(as_text=True)
    assert 'href="/speakers/new"' in body


def test_run_step_submits_bridge_job(client, app, login, csrf):
    login()
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    response = client.post("/speakers/speaker-a/setup/7",
                           headers={"X-CSRF-Token": csrf(client)}, data={"op": "run"})
    assert response.status_code == 303
    assert runner.actions[0][0] == "bridge"


def test_run_step_does_not_mark_done(client, app, login, csrf, settings):
    from webui.wizard import load_progress

    login()
    app.extensions["jobs"] = FakeRunner()
    response = client.post("/speakers/speaker-a/setup/7",
                           headers={"X-CSRF-Token": csrf(client)}, data={"op": "run"})
    assert response.status_code == 303
    progress = load_progress(settings.state_dir / "setup" / "speaker-a.json")
    assert "bridge" not in progress.done
    assert progress.step == 2
    assert progress.last_job == "job-1"


def test_route_step_writes_profile_and_token(client, app, login, csrf, settings):
    login()
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    save_providers(settings.state_dir / "providers.json",
                   [Provider("flai", "FLAI", "http://10.0.0.2:5000/v1", ("flai-chat",))])
    (settings.secrets_dir / "flai-token-speaker-a").write_text("upstream\n", encoding="utf-8")
    response = client.post("/speakers/speaker-a/setup/6",
                           headers={"X-CSRF-Token": csrf(client)}, data={
        "op": "run", "provider_id": "flai", "model": "flai-chat",
        "api_key_file": "flai-token-speaker-a",
    })
    assert response.status_code == 303
    profile = (settings.speakers_dir / "speaker-a.env").read_text(encoding="utf-8")
    assert "LLM_TOKEN_FILE=secrets/router-token-speaker-a" in profile
    assert (settings.secrets_dir / "router-token-speaker-a").is_file()
    assert runner.actions[0][0] == "key"


def test_setup_step6_allows_keyless_route(client, app, login, csrf, settings):
    login()
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    save_providers(
        settings.state_dir / "providers.json",
        [Provider("local", "Local", "http://127.0.0.1:11434/v1", ("llama",))],
    )
    response = client.post(
        "/speakers/speaker-a/setup/6",
        headers={"X-CSRF-Token": csrf(client)},
        data={"op": "run", "provider_id": "local", "model": "llama", "api_key_file": ""},
    )
    assert response.status_code == 303
    raw = json.loads(settings.router_config.read_text(encoding="utf-8"))
    assert raw["routes"][0]["primary"]["api_key_file"] == ""


def test_done_survives_reload(client, login, csrf, settings):
    from webui.wizard import load_progress

    login()
    client.post("/speakers/speaker-a/setup/2",
                headers={"X-CSRF-Token": csrf(client)}, data={"op": "done"})
    progress = load_progress(settings.state_dir / "setup" / "speaker-a.json")
    assert "bind" in progress.done
    assert progress.step == 3


def test_root_step_submits_adb_job(client, app, login, csrf):
    login()
    runner = FakeRunner()
    app.extensions["jobs"] = runner
    response = client.post("/speakers/speaker-a/setup/4",
                           headers={"X-CSRF-Token": csrf(client)}, data={"op": "run"})
    assert response.status_code == 303
    assert runner.actions[0][0] == "adb"
