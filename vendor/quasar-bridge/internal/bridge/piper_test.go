package bridge

import (
	"strings"
	"testing"
)

func TestSpeakPiperQueuesAudioURL(t *testing.T) {
	t.Setenv("QUASAR_TTS_PIPER_URL", "http://192.168.1.2:8083/")
	n, _ := testNative(t)
	p := &nativeRequest{ctx: t.Context(), id: "piper-request"}
	n.requests[p.id] = p
	t.Cleanup(func() { delete(n.requests, p.id) })

	if err := n.speakPiper(p, "Готовый ответ"); err != nil {
		t.Fatal(err)
	}
	if !n.hasSilentPlayback(p) {
		t.Fatal("piper answer must suppress the station TTS")
	}
	directives := n.takeSound(p)
	if len(directives) != 1 || directives[0].GetName() != "audio_play" {
		t.Fatalf("unexpected directives: %+v", directives)
	}
	stream, ok := directives[0].GetPayload().AsMap()["stream"].(map[string]any)
	if !ok {
		t.Fatalf("no stream in payload: %v", directives[0].GetPayload().AsMap())
	}
	link, _ := stream["url"].(string)
	if !strings.HasPrefix(link, "http://192.168.1.2:8083/say.wav?text=") {
		t.Fatalf("unexpected piper url: %q", link)
	}
	if !strings.Contains(link, "%D0") {
		t.Fatalf("text is not url-encoded: %q", link)
	}
}

func TestSpeakPiperStripsMarkdown(t *testing.T) {
	t.Setenv("QUASAR_TTS_PIPER_URL", "http://192.168.1.2:8083")
	n, _ := testNative(t)
	p := &nativeRequest{ctx: t.Context(), id: "piper-markdown"}
	n.requests[p.id] = p
	t.Cleanup(func() { delete(n.requests, p.id) })

	if err := n.speakPiper(p, "Валерию **49 лет**."); err != nil {
		t.Fatal(err)
	}
	directives := n.takeSound(p)
	stream, _ := directives[0].GetPayload().AsMap()["stream"].(map[string]any)
	link, _ := stream["url"].(string)
	if strings.Contains(link, "%2A") || strings.Contains(link, "%23") {
		t.Fatalf("markdown leaked into the piper url: %q", link)
	}
	if !strings.Contains(link, "49") {
		t.Fatalf("text is missing from the piper url: %q", link)
	}
}

func TestPiperSpeechURLRejectsEmptyConfig(t *testing.T) {
	t.Setenv("QUASAR_TTS_PIPER_URL", "")
	if _, err := piperSpeechURL("текст"); err == nil {
		t.Fatal("piper must be disabled without a URL")
	}
	t.Setenv("QUASAR_TTS_PIPER_URL", "http://192.168.1.2:8083")
	if _, err := piperSpeechURL("   "); err == nil {
		t.Fatal("empty text must be rejected")
	}
	if _, err := piperSpeechURL(strings.Repeat("слово ", 200)); err == nil {
		t.Fatal("long text must fall back to the station TTS")
	}
}
