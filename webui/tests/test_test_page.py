from types import SimpleNamespace

from webui.tests.test_app import FakeRunner


class JobRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.job = SimpleNamespace(id="job-9", action="check", target="speaker-a",
                                   status="succeeded", created_at="2026-11-06T10:00:00+00:00",
                                   log_path=None)

    def get(self, job_id):
        return self.job if job_id == "job-9" else None

    def tail(self, job_id, offset):
        return "лог проверки", 10


def test_test_page_has_three_cards(client, login):
    login()
    body = client.get("/test").get_data(as_text=True)
    assert "Голос" in body and "LLM" in body and "Bridge" in body
    assert 'class="grid cards test-grid"' in body
    assert body.count('class="field-inline"') == 3


def test_check_creates_job(client, app, login, csrf):
    login()
    runner = JobRunner()
    app.extensions["jobs"] = runner
    response = client.post("/test/check", headers={"X-CSRF-Token": csrf(client)},
                           data={"speaker": "speaker-a"})
    assert response.status_code == 303
    assert runner.actions[0][0] == "check"
    assert runner.actions[0][1].name == "speaker-a"


def test_test_page_embeds_job_log(client, app, login):
    login()
    app.extensions["jobs"] = JobRunner()
    body = client.get("/test?job=job-9").get_data(as_text=True)
    assert "лог проверки" in body


def test_job_log_endpoint_redacts_secret(client, app, login):
    login()
    secret = "flai-verysecrettokenvalue"
    settings = app.config["WEBUI_SETTINGS"]
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    (settings.secrets_dir / "flai-token-speaker-a").write_text(secret, encoding="utf-8")

    class Runner:
        def get(self, job_id):
            return SimpleNamespace(
                id="job-7", action="check", target="speaker-a",
                status="succeeded", created_at="2026-11-06T10:00:00+00:00",
                log_path=None,
            )

        def tail(self, job_id, offset):
            return f"output {secret} done", 100

    app.extensions["jobs"] = Runner()
    body = client.get("/jobs/job-7/log").get_data(as_text=True)
    assert secret not in body
    assert "***" in body
