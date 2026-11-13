package bridge

import (
	"strings"
	"testing"
	"time"
)

func TestCleanSpeechText(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want string
	}{
		{"bold", "**bold**", "bold"},
		{"italic", "*italic*", "italic"},
		{"bold italic", "***both***", "both"},
		{"link", "[text](https://example.com)", "text"},
		{"image", "![alt](img.jpg)", ""},
		{"inline code", "text `code` here", "text code here"},
		{"heading", "## Title", "Title"},
		{"quote", "> quote", "quote"},
		{"unordered list", "- item", "item"},
		{"ordered list", "1. item", "item"},
		{"task list", "- [x] done", "done"},
		{"strikethrough", "~~strike~~", "strike"},
		{"html", "<b>text</b>", "text"},
		{"entity", "&nbsp;text &amp; more", "text & more"},
		{"bare url", "https://example.com", ""},
		{"exponentiation", "3**2=9", "3**2=9"},
		{"variable", "some_var", "some_var"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := cleanSpeechText(tt.in); got != tt.want {
				t.Fatalf("got %q, want %q", got, tt.want)
			}
		})
	}
}

func TestCleanSpeechTextFencedCode(t *testing.T) {
	got := cleanSpeechText("before\n```\ncode block\n```\nafter")
	if strings.Contains(got, "code block") || !strings.Contains(got, "before") || !strings.Contains(got, "after") {
		t.Fatalf("unexpected: %q", got)
	}
}

func TestCleanSpeechTextTable(t *testing.T) {
	got := cleanSpeechText("| a | b |\n|---|---|\n| 1 | 2 |")
	if strings.Contains(got, "|") || strings.Contains(got, "---") || !strings.Contains(got, "a") || !strings.Contains(got, "2") {
		t.Fatalf("unexpected: %q", got)
	}
}

func TestClearFillersDropsQueuedFillers(t *testing.T) {
	n := &Native{}
	p := &nativeRequest{speechQueue: []speechItem{
		{text: "filler-1", filler: true},
		{text: "answer", filler: false},
		{text: "filler-2", filler: true},
	}}

	n.clearFillers(p)

	if len(p.speechQueue) != 1 || p.speechQueue[0].text != "answer" || p.speechQueue[0].filler {
		t.Fatalf("queue=%#v", p.speechQueue)
	}
	if !p.fillersStopped {
		t.Fatal("fillers were not stopped")
	}
}

func TestStreamBufferKeepsSentencesIntact(t *testing.T) {
	buf := newStreamBuffer(500)
	text := "Согласно информации из загруженного документа, ему сорок девять лет. Он родился двадцать восьмого декабря. Это написано в документе."
	var got []string
	got = append(got, buf.Add(text)...)
	got = append(got, buf.Flush()...)

	if len(got) == 0 || got[0] != "Согласно информации из загруженного документа, ему сорок девять лет." {
		t.Fatalf("first chunk must be the whole first sentence: %#v", got)
	}
	for _, chunk := range got {
		if !strings.HasSuffix(chunk, ".") && !strings.HasSuffix(chunk, "!") && !strings.HasSuffix(chunk, "?") && !strings.HasSuffix(chunk, "…") {
			t.Fatalf("chunk is not a whole sentence: %q", chunk)
		}
	}
	if len(got) < 2 {
		t.Fatalf("expected a merged tail, got %#v", got)
	}
}

func TestStreamBufferMergesShortSentencesAfterTheFirst(t *testing.T) {
	buf := newStreamBuffer(500)
	text := "Первое. " + strings.Repeat("Короткое предложение. ", 12)
	var got []string
	got = append(got, buf.Add(text)...)
	got = append(got, buf.Flush()...)

	if len(got) == 0 || got[0] != "Первое." {
		t.Fatalf("first chunk=%#v", got)
	}
	if len(got) >= 12 {
		t.Fatalf("short sentences were not merged: %d chunks", len(got))
	}
}

func TestSpeechFillerConfig(t *testing.T) {
	t.Setenv("QUASAR_SPEECH_FILLER", "1")
	t.Setenv("QUASAR_SPEECH_FILLER_AFTER", "7")
	t.Setenv("QUASAR_SPEECH_FILLER_EVERY", "9")
	t.Setenv("QUASAR_SPEECH_FILLER_MAX", "2")
	t.Setenv("QUASAR_SPEECH_FILLERS", "раз| два |")

	if !speechFillerEnabled() {
		t.Fatal("fillers not enabled")
	}
	if got := speechFillerAfter(); got != 7*time.Second {
		t.Fatalf("after=%v", got)
	}
	if got := speechFillerEvery(); got != 9*time.Second {
		t.Fatalf("every=%v", got)
	}
	if got := speechFillerMax(); got != 2 {
		t.Fatalf("max=%d", got)
	}
	if got := speechFillerPhrases(); len(got) != 2 || got[0] != "раз" || got[1] != "два" {
		t.Fatalf("phrases=%#v", got)
	}
}

func TestSpeechFillerDefaults(t *testing.T) {
	t.Setenv("QUASAR_SPEECH_FILLERS", "")
	if got := speechFillerPhrases(); len(got) == 0 {
		t.Fatal("default phrases are empty")
	}
}

func TestStreamBufferSplitsSentences(t *testing.T) {
	b := newStreamBuffer(500)
	var got []string
	got = append(got, b.Add("При")...)
	got = append(got, b.Add("вет. Как ")...)
	got = append(got, b.Add("дела?")...)
	got = append(got, b.Flush()...)

	if len(got) != 2 || got[0] != "Привет." || got[1] != "Как дела?" {
		t.Fatalf("got %#v", got)
	}
}

func TestStreamBufferKeepsDecimalAndURL(t *testing.T) {
	b := newStreamBuffer(500)
	var got []string
	got = append(got, b.Add("3.14 — это число. Сайт example.com работает. ")...)
	got = append(got, b.Flush()...)

	if len(got) != 2 {
		t.Fatalf("got %#v", got)
	}
	if !strings.Contains(got[0], "3.14") || strings.HasPrefix(got[0], "3.") && len(got[0]) < 5 {
		t.Fatalf("decimal split: %#v", got)
	}
	if !strings.Contains(got[1], "example.com") {
		t.Fatalf("url split: %#v", got)
	}
}

func TestStreamBufferKeepsClosingQuote(t *testing.T) {
	b := newStreamBuffer(500)
	got := b.Add("«Привет!» Как дела? ")
	got = append(got, b.Flush()...)

	if len(got) != 2 || !strings.Contains(got[0], "»") || got[1] != "Как дела?" {
		t.Fatalf("got %#v", got)
	}
}

func TestStreamBufferAbbreviation(t *testing.T) {
	b := newStreamBuffer(500)
	got := b.Add("т.е. это пример. Готово. ")
	got = append(got, b.Flush()...)

	if len(got) != 2 || got[0] != "т.е. это пример." || got[1] != "Готово." {
		t.Fatalf("got %#v", got)
	}
}

func TestStreamBufferFlushesRemainder(t *testing.T) {
	b := newStreamBuffer(500)
	if got := b.Add("Незаконченная фраза"); len(got) != 0 {
		t.Fatalf("unexpected early chunks: %#v", got)
	}
	got := b.Flush()
	if len(got) != 1 || got[0] != "Незаконченная фраза" {
		t.Fatalf("got %#v", got)
	}
}

func TestStreamBufferCutsLongSentence(t *testing.T) {
	b := newStreamBuffer(40)
	got := b.Add(strings.Repeat("слово ", 100))
	got = append(got, b.Flush()...)

	if len(got) < 2 {
		t.Fatalf("expected several chunks, got %#v", got)
	}
	for _, chunk := range got {
		if len([]rune(chunk)) > 40 {
			t.Fatalf("chunk too long: %d %q", len([]rune(chunk)), chunk)
		}
	}
}
