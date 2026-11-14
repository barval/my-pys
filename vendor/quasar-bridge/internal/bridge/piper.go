package bridge

import (
	"errors"
	"net/url"
	"os"
	"strings"

	"quasarbridge/internal/sound"
)

// Прототип локального синтеза: Piper на хосте отдаёт WAV по GET /say.wav,
// а станция забирает его по URL в директиве audio_play. Включается
// переменной QUASAR_TTS_PIPER_URL; без неё работает штатный TTS станции.

func piperBaseURL() string {
	return strings.TrimSpace(os.Getenv("QUASAR_TTS_PIPER_URL"))
}

// piperMaxChars — предел текста для одного запроса Piper: длинный ответ не
// влезает в URL и лимит сервиса, поэтому его озвучивает станция.
func piperMaxChars() int {
	return envPositiveInt("QUASAR_TTS_PIPER_MAX_CHARS", 900)
}

// piperSpeechURL собирает ссылку на синтез: станция скачивает её сама.
func piperSpeechURL(text string) (string, error) {
	base := piperBaseURL()
	if base == "" {
		return "", errors.New("piper is not configured")
	}
	text = strings.TrimSpace(text)
	if text == "" {
		return "", errors.New("piper text is empty")
	}
	if len([]rune(text)) > piperMaxChars() {
		return "", errors.New("piper text is too long")
	}
	return strings.TrimRight(base, "/") + "/say.wav?text=" + url.QueryEscape(text), nil
}

// speakPiper озвучивает ответ локальным синтезом: станции отправляется
// директива audio_play со ссылкой на WAV. Markdown вычищается, иначе Piper
// читает звёздочки и решётки.
func (n *Native) speakPiper(p *nativeRequest, text string) error {
	link, err := piperSpeechURL(cleanSpeechText(text))
	if err != nil {
		return err
	}
	return n.queueSound(p.ctx, p, sound.Request{URL: link, Title: "Piper"})
}
