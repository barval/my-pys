package bridge

import (
	"os"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const (
	defaultSpeechChunkChars = 500
	defaultSpeechChunkLimit = 6
)

func speechChunkChars() int {
	return envPositiveInt("QUASAR_SPEECH_MAX_CHARS", defaultSpeechChunkChars)
}

func streamLLMEnabled() bool {
	return os.Getenv("QUASAR_STREAM_LLM") == "1"
}

func speechChunkLimit() int {
	return envPositiveInt("QUASAR_SPEECH_MAX_CHUNKS", defaultSpeechChunkLimit)
}

// speechChunkStep — целевой размер второго куска. Дальше куски удваиваются
// до QUASAR_SPEECH_MAX_CHARS: на длинном ответе это уменьшает число TTS-
// запросов, не разрезая предложения.
func speechChunkStep() int {
	return envPositiveInt("QUASAR_SPEECH_STEP_CHARS", 160)
}

// speechChunkTarget — целевой размер куска по его номеру. Первый кусок —
// всегда одно законченное предложение: резать его по символам нельзя.
func speechChunkTarget(index, maxChars int) int {
	if index <= 0 {
		return maxChars
	}
	limit := speechChunkStep()
	for i := 1; i < index && limit < maxChars; i++ {
		limit *= 2
	}
	if limit > maxChars {
		limit = maxChars
	}
	return limit
}

func speechFillerEnabled() bool {
	return os.Getenv("QUASAR_SPEECH_FILLER") == "1"
}

func speechFillerAfter() time.Duration {
	return time.Duration(envPositiveInt("QUASAR_SPEECH_FILLER_AFTER", 10)) * time.Second
}

func speechFillerEvery() time.Duration {
	return time.Duration(envPositiveInt("QUASAR_SPEECH_FILLER_EVERY", 15)) * time.Second
}

func speechFillerMax() int {
	return envPositiveInt("QUASAR_SPEECH_FILLER_MAX", 3)
}

// speechFillerCancelWindow — сколько секунд после отправки заполнителя ещё
// имеет смысл закрывать его TTS-поток. Станция закрывает поток сразу после
// выдачи текста, но само аудио может звучать ещё несколько секунд.
func speechFillerCancelWindow() time.Duration {
	return time.Duration(envPositiveInt("QUASAR_SPEECH_FILLER_CANCEL_SECONDS", 10)) * time.Second
}

func speechFillerPhrases() []string {
	raw := strings.TrimSpace(os.Getenv("QUASAR_SPEECH_FILLERS"))
	if raw == "" {
		return []string{
			"Секунду, ищу ответ.",
			"Пока думаю.",
			"Мне нужно чуть больше времени.",
			"Ещё немного, и смогу сказать.",
		}
	}
	var phrases []string
	for _, part := range strings.Split(raw, "|") {
		if phrase := strings.TrimSpace(part); phrase != "" {
			phrases = append(phrases, phrase)
		}
	}
	return phrases
}

func envPositiveInt(name string, fallback int) int {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n < 1 {
		return fallback
	}
	return n
}

// splitSpeech cuts a voice answer into chunks at sentence boundaries where
// possible. A single sentence longer than maxChars is split at word boundaries.
// The final chunk gets an ellipsis when maxChunks hides the rest of the answer.
func splitSpeech(text string, maxChars, maxChunks int) []string {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil
	}
	if maxChars < 1 {
		maxChars = defaultSpeechChunkChars
	}
	if maxChunks < 1 {
		maxChunks = defaultSpeechChunkLimit
	}

	sentences := splitSentences(text)
	if len(sentences) == 0 {
		sentences = []string{text}
	}

	var chunks []string
	var current strings.Builder
	currentLen := 0
	flush := func() {
		if currentLen == 0 {
			return
		}
		chunks = append(chunks, strings.TrimSpace(current.String()))
		current.Reset()
		currentLen = 0
	}

	for _, sentence := range sentences {
		runes := []rune(sentence)
		if len(runes) > maxChars {
			flush()
			chunks = append(chunks, splitWords(runes, maxChars)...)
			continue
		}
		add := len(runes)
		if currentLen > 0 {
			add++
		}
		if currentLen > 0 && currentLen+add > maxChars {
			flush()
		}
		if currentLen > 0 {
			current.WriteByte(' ')
			currentLen++
		}
		current.WriteString(sentence)
		currentLen += len(runes)
	}
	flush()

	if len(chunks) == 0 {
		chunks = []string{text}
	}
	if len(chunks) > maxChunks {
		chunks = chunks[:maxChunks]
		chunks[len(chunks)-1] = strings.TrimRight(chunks[len(chunks)-1], " ") + "…"
	}
	return chunks
}

// splitSpeechAdaptive делит ответ по границам предложений: первый кусок —
// ровно первое предложение, дальше предложения склеиваются до целевого
// размера (160, 320, затем maxChars). Внутри предложения текст режется
// только если само предложение длиннее maxChars.
func splitSpeechAdaptive(text string, maxChars, maxChunks int) []string {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil
	}
	if maxChars < 1 {
		maxChars = defaultSpeechChunkChars
	}
	if maxChunks < 1 {
		maxChunks = defaultSpeechChunkLimit
	}
	sentences := splitSentences(text)
	if len(sentences) == 0 {
		sentences = []string{text}
	}
	var chunks []string
	var current []string
	size := 0
	flush := func() {
		if size == 0 {
			return
		}
		chunks = append(chunks, strings.TrimSpace(strings.Join(current, " ")))
		current = nil
		size = 0
	}
	for _, sentence := range sentences {
		runes := []rune(sentence)
		if len(runes) > maxChars {
			flush()
			chunks = append(chunks, splitWords(runes, maxChars)...)
			continue
		}
		if size == 0 {
			current = []string{sentence}
			size = len(runes)
			if len(chunks) == 0 {
				flush()
			}
			continue
		}
		if size >= speechChunkTarget(len(chunks), maxChars) || size+1+len(runes) > maxChars {
			flush()
			current = []string{sentence}
			size = len(runes)
			continue
		}
		current = append(current, sentence)
		size += 1 + len(runes)
	}
	flush()
	if len(chunks) == 0 {
		chunks = []string{text}
	}
	if len(chunks) > maxChunks {
		chunks = chunks[:maxChunks]
		chunks[len(chunks)-1] = strings.TrimRight(chunks[len(chunks)-1], " ") + "…"
	}
	return chunks
}

func splitSentences(text string) []string {
	var out []string
	var b strings.Builder
	runes := []rune(text)
	for i, r := range runes {
		b.WriteRune(r)
		if r != '.' && r != '!' && r != '?' && r != '…' {
			continue
		}
		if i+1 == len(runes) || unicode.IsSpace(runes[i+1]) {
			if sentence := strings.TrimSpace(b.String()); sentence != "" {
				out = append(out, sentence)
			}
			b.Reset()
		}
	}
	if sentence := strings.TrimSpace(b.String()); sentence != "" {
		out = append(out, sentence)
	}
	return out
}

func splitWords(text []rune, maxChars int) []string {
	words := strings.Fields(string(text))
	var out []string
	var current []string
	currentLen := 0

	for _, word := range words {
		runes := []rune(word)
		if len(runes) > maxChars {
			if len(current) > 0 {
				out = append(out, strings.Join(current, " "))
				current = nil
				currentLen = 0
			}
			for len(runes) > maxChars {
				out = append(out, string(runes[:maxChars]))
				runes = runes[maxChars:]
			}
			if len(runes) > 0 {
				current = []string{string(runes)}
				currentLen = len(runes)
			}
			continue
		}

		add := len(runes)
		if currentLen > 0 {
			add++
		}
		if currentLen > 0 && currentLen+add > maxChars {
			out = append(out, strings.Join(current, " "))
			current = nil
			currentLen = 0
		}
		if currentLen > 0 {
			currentLen++
		}
		current = append(current, string(runes))
		currentLen += len(runes)
	}

	if len(current) > 0 {
		out = append(out, strings.Join(current, " "))
	}
	return out
}
