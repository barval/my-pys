.PHONY: help check firmware stand stop bridge ssh status check-backends resolve routing key routes flai-log router-init router router-stop router-logs router-status router-test lint webui webui-dev webui-stop webui-logs webui-passwd webui-test

WEBUI_UID ?= $(shell id -u)
WEBUI_GID ?= $(shell id -g)
DOCKER_GID ?= $(shell stat -c '%g' /var/run/docker.sock 2>/dev/null || echo 988)
export WEBUI_UID WEBUI_GID DOCKER_GID

help:
	@echo "make check     — проверить внешнюю LLM"
	@echo "make firmware  — скачать прошивку .46"
	@echo "make stand     — запустить lite-kit в Docker"
	@echo "make stop      — остановить lite-kit"
	@echo "make bridge    — установить Quasar Bridge (интерактивно)"
	@echo "make resolve   — найти колонку по MAC/device ID"
	@echo "make routing   — применить политику маршрутизации"
	@echo "make key       — записать ключ LLM из профиля в колонку"
	@echo "make ssh       — войти на колонку по ключу"
	@echo "make status    — статус процесса Bridge (без запроса к LLM)"
	@echo "make check-backends — проверить LLM (создаёт тестовую сессию)"
	@echo "make routes    — последние решения Bridge: llm или yandex"
	@echo "make flai-log  — последние запросы в FLAI"
	@echo "make router-init — создать ключи и конфиг роутера"
	@echo "make router    — собрать и запустить LLM-роутер на 5002"
	@echo "make router-stop — остановить роутер"
	@echo "make router-logs — логи роутера"
	@echo "make router-status — health роутера"
	@echo "make router-test — тесты роутера"
	@echo "make webui     — собрать и запустить панель в Docker"
	@echo "make webui-passwd — задать пароль панели"
	@echo "make webui-stop — остановить панель"
	@echo "make webui-logs — логи панели"
	@echo "make webui-dev — панель на хосте (для разработки)"
	@echo "make webui-test — тесты панели"
	@echo "make lint      — bash -n для скриптов"

check:
	./scripts/check-llm.sh

firmware:
	./scripts/fetch-firmware.sh

stand:
	./scripts/start-lite-kit.sh

stop:
	./scripts/stop-lite-kit.sh

bridge:
	./scripts/install-quasar-bridge.sh

resolve:
	./scripts/resolve-speaker.sh

routing:
	./scripts/apply-bridge-routing.sh

key:
	./scripts/set-speaker-key.sh

ssh:
	ssh -i secrets/speaker_ed25519 -p 2222 root@$$(./scripts/resolve-speaker.sh)

status:
	ssh -i secrets/speaker_ed25519 -p 2222 root@$$(./scripts/resolve-speaker.sh) \
	  'pkg=/data/opt/quasar-bridge/app; sh "$$pkg/control.sh" status'

check-backends:
	ssh -i secrets/speaker_ed25519 -p 2222 root@$$(./scripts/resolve-speaker.sh) \
	  'pkg=/data/opt/quasar-bridge/app; sh "$$pkg/control.sh" check-backends'

routes:
	ssh -i secrets/speaker_ed25519 -p 2222 root@$$(./scripts/resolve-speaker.sh) \
	  'tail -n 300 /data/opt/quasar-bridge/service.log' | grep native_route_decision | tail -20

flai-log:
	docker logs --since 10m flai-web 2>&1 | grep -E "query=|/v1/chat/completions" | tail -30

router-init:
	./scripts/router-init.sh

router:
	./scripts/start-router.sh

router-stop:
	./scripts/stop-router.sh

router-logs:
	docker logs -f llm-router

router-status:
	curl -fsS http://192.168.1.2:5002/health

router-test:
	pytest router/tests/test_router.py -q

webui:
	@mkdir -p secrets local/speakers webui-state backups .cache vendor/lite-kit/firmware
	docker compose -f docker/docker-compose.webui.yml up -d --build --force-recreate

webui-dev:
	python3 -m webui

webui-stop:
	docker compose -f docker/docker-compose.webui.yml down

webui-logs:
	docker compose -f docker/docker-compose.webui.yml logs -f webui

webui-passwd:
	docker compose -f docker/docker-compose.webui.yml run --rm --no-deps webui python -m webui.admin set-password

webui-test:
	python3 -m pytest webui/tests -q

lint:
	bash -n scripts/*.sh
