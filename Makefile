.PHONY: help check firmware stand stop bridge ssh status resolve lint

help:
	@echo "make check     — проверить FLAI"
	@echo "make firmware  — скачать прошивку .46"
	@echo "make stand     — запустить lite-kit в Docker"
	@echo "make stop      — остановить lite-kit"
	@echo "make bridge    — установить Quasar Bridge (интерактивно)"
	@echo "make resolve   — найти колонку по MAC/device ID"
	@echo "make ssh       — войти на колонку по ключу"
	@echo "make status    — статус Bridge на колонке"
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

lint:
	bash -n scripts/*.sh
