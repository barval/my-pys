.PHONY: help check firmware stand stop bridge ssh status resolve routes flai-log lint

help:
	@echo "make check     — проверить FLAI"
	@echo "make firmware  — скачать прошивку .46"
	@echo "make stand     — запустить lite-kit в Docker"
	@echo "make stop      — остановить lite-kit"
	@echo "make bridge    — установить Quasar Bridge (интерактивно)"
	@echo "make resolve   — найти колонку по MAC/device ID"
	@echo "make ssh       — войти на колонку по ключу"
	@echo "make status    — статус Bridge на колонке"
	@echo "make routes    — последние решения Bridge: llm или yandex"
	@echo "make flai-log  — последние запросы в FLAI"
	@echo "make lint      — bash -n для скриптов"

check:
	./scripts/check-flai.sh

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

ssh:
	ssh -i secrets/speaker_ed25519 -p 2222 root@$$(./scripts/resolve-speaker.sh)

status:
	ssh -i secrets/speaker_ed25519 -p 2222 root@$$(./scripts/resolve-speaker.sh) \
	  'pkg=/data/opt/quasar-bridge/app; sh "$$pkg/control.sh" status; sh "$$pkg/control.sh" check-backends'

routes:
	ssh -i secrets/speaker_ed25519 -p 2222 root@$$(./scripts/resolve-speaker.sh) \
	  'tail -n 300 /data/opt/quasar-bridge/service.log' | grep native_route_decision | tail -20

flai-log:
	docker logs --since 10m flai-web 2>&1 | grep -E "query=|/v1/chat/completions" | tail -30

lint:
	bash -n scripts/*.sh
