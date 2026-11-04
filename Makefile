.PHONY: help check firmware stand stop bridge ssh status lint

help:
	@echo "make check     — проверить FLAI"
	@echo "make firmware  — скачать прошивку .46"
	@echo "make stand     — запустить lite-kit в Docker"
	@echo "make stop      — остановить lite-kit"
	@echo "make bridge    — установить Quasar Bridge (интерактивно)"
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

ssh:
	ssh -i secrets/speaker_ed25519 -p 2222 root@192.168.1.103

status:
	ssh -i secrets/speaker_ed25519 -p 2222 root@192.168.1.103 \
	  'pkg=/data/opt/quasar-bridge/app; sh "$$pkg/control.sh" status; sh "$$pkg/control.sh" check-backends'

lint:
	bash -n scripts/*.sh
