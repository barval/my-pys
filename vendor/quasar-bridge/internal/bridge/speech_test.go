package bridge

import (
	"strings"
	"testing"
)

func TestSplitSpeechKeepsCompleteSentences(t *testing.T) {
	chunks := splitSpeech("Первое предложение. Второе предложение. Третье предложение.", 30, 10)

	if len(chunks) < 2 {
		t.Fatalf("expected several chunks, got %d: %#v", len(chunks), chunks)
	}
	for _, chunk := range chunks {
		if len([]rune(chunk)) > 30 {
			t.Fatalf("chunk longer than limit: %d: %q", len([]rune(chunk)), chunk)
		}
		if !strings.HasSuffix(chunk, ".") {
			t.Fatalf("sentence boundary lost: %q", chunk)
		}
	}
}

func TestSplitSpeechSplitsLongSentenceAtWords(t *testing.T) {
	text := strings.TrimSpace(strings.Repeat("очень длинное предложение ", 30))
	chunks := splitSpeech(text, 40, 20)

	if len(chunks) < 2 {
		t.Fatalf("expected several chunks, got %d", len(chunks))
	}
	for _, chunk := range chunks {
		if len([]rune(chunk)) > 40 {
			t.Fatalf("chunk longer than limit: %d: %q", len([]rune(chunk)), chunk)
		}
		if strings.HasPrefix(chunk, " ") || strings.HasSuffix(chunk, " ") {
			t.Fatalf("chunk has edge spaces: %q", chunk)
		}
	}
}

func TestSplitSpeechCapsNumberOfChunks(t *testing.T) {
	text := "Один. Два. Три. Четыре. Пять. Шесть. Семь. Восемь."
	chunks := splitSpeech(text, 10, 3)

	if len(chunks) != 3 {
		t.Fatalf("expected 3 chunks, got %d: %#v", len(chunks), chunks)
	}
	if !strings.HasSuffix(chunks[len(chunks)-1], "…") {
		t.Fatalf("last chunk is not marked as truncated: %q", chunks[len(chunks)-1])
	}
}

func TestSplitSpeechEmpty(t *testing.T) {
	if chunks := splitSpeech("   ", 100, 3); len(chunks) != 0 {
		t.Fatalf("expected no chunks, got %#v", chunks)
	}
}

func TestSpeechLimitsFromEnvironment(t *testing.T) {
	t.Setenv("QUASAR_SPEECH_MAX_CHARS", "432")
	t.Setenv("QUASAR_SPEECH_MAX_CHUNKS", "4")

	if got := speechChunkChars(); got != 432 {
		t.Fatalf("chars=%d", got)
	}
	if got := speechChunkLimit(); got != 4 {
		t.Fatalf("limit=%d", got)
	}
}

func TestSpeechLimitsRejectInvalidValues(t *testing.T) {
	t.Setenv("QUASAR_SPEECH_MAX_CHARS", "0")
	t.Setenv("QUASAR_SPEECH_MAX_CHUNKS", "nope")

	if got := speechChunkChars(); got != 500 {
		t.Fatalf("chars=%d", got)
	}
	if got := speechChunkLimit(); got != 6 {
		t.Fatalf("limit=%d", got)
	}
}
