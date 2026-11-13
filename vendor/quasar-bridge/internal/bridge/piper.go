package bridge

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"quasarbridge/internal/sound"
)

// Прототип локального синтеза: Piper на хосте отдаёт WAV, Bridge кладёт его
// в каталог звуков станции и просит проиграть как локальный файл. Включается
// переменной QUASAR_TTS_PIPER_URL, без неё работает штатный TTS станции.

const (
	piperTimeout  = 20 * time.Second
	piperMaxBytes = 8 << 20
)

func piperBaseURL() string {
	return strings.TrimSpace(os.Getenv("QUASAR_TTS_PIPER_URL"))
}

func piperDir() string {
	if dir := strings.TrimSpace(os.Getenv("QUASAR_TTS_PIPER_DIR")); dir != "" {
		return dir
	}
	return "/data/quasar/data/sounds"
}

// piperSpeech синтезирует текст и возвращает имя файла для директивы
// local_audio_file_play. Имя детерминировано по тексту, поэтому повторный
// ответ не плодит файлы.
func piperSpeech(ctx context.Context, text string) (string, error) {
	base := piperBaseURL()
	if base == "" {
		return "", errors.New("piper is not configured")
	}
	text = strings.TrimSpace(text)
	if text == "" {
		return "", errors.New("piper text is empty")
	}
	payload, err := json.Marshal(map[string]string{"text": text})
	if err != nil {
		return "", err
	}
	requestCtx, cancel := context.WithTimeout(ctx, piperTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(requestCtx, http.MethodPost, strings.TrimRight(base, "/")+"/say", bytes.NewReader(payload))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", errors.New("piper returned HTTP " + resp.Status)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, piperMaxBytes+1))
	if err != nil {
		return "", err
	}
	if len(data) > piperMaxBytes {
		return "", errors.New("piper audio is too large")
	}
	if len(data) < 44 || string(data[:4]) != "RIFF" {
		return "", errors.New("piper returned no WAV audio")
	}
	sum := sha256.Sum256([]byte(text))
	name := "piper-" + hex.EncodeToString(sum[:8]) + ".wav"
	dir := piperDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(filepath.Join(dir, name), data, 0o644); err != nil {
		return "", err
	}
	return name, nil
}

// speakPiper озвучивает ответ локальным синтезом: файл кладётся в каталог
// звуков, а станции отправляется директива проигрывания этого файла.
func (n *Native) speakPiper(p *nativeRequest, text string) error {
	name, err := piperSpeech(p.ctx, text)
	if err != nil {
		return err
	}
	return n.queueSound(p.ctx, p, sound.Request{File: name})
}
