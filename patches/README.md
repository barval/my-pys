# Патчи для внешних компонентов

## flai-camera-invocation.patch

Необязательный патч для локального FLAI. Он заставляет задачу камеры
вырезать служебное обращение («спроси у ФЛАЙ», «спроси нейросеть») перед
передачей вопроса vision-модели.

Основное решение — прокси `docker/flai_invocation_proxy.py`; этот патч
нужен как второй слой, если запрос всё же дошёл до FLAI с обращением.

Применение:

```bash
cd /home/GIT/GITEA/BARVAL-MY/flai
git apply /home/GIT/GITEA/BARVAL-MY/my-pys/patches/flai-camera-invocation.patch
docker restart flai-web
```

Патч живёт вне этого репозитория и может быть потерян при обновлении FLAI.
После обновления проверьте `git -C /home/GIT/GITEA/BARVAL-MY/flai diff`.
