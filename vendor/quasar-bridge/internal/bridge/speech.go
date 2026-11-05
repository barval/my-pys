package bridge

import (
	"os"
	"strconv"
	"strings"
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
