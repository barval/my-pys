package bridge

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	fileplayer "github.com/freequasar/quasar-go-genproto/proto/alice/protos/endpoint/capabilities/audio_file_player"
	"google.golang.org/protobuf/proto"
	"quasarbridge/internal/sound"
)

func testWAV() []byte {
	data := make([]byte, 48)
	copy(data, "RIFF")
	copy(data[8:], "WAVEfmt ")
	return data
}

func TestPiperSpeechSavesWav(t *testing.T) {
	wav := testWAV()
	var gotText string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/say" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		var payload map[string]string
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Errorf("invalid payload: %v", err)
		}
		gotText = payload["text"]
		w.Header().Set("Content-Type", "audio/wav")
		_, _ = w.Write(wav)
	}))
	defer server.Close()

	dir := t.TempDir()
	t.Setenv("QUASAR_TTS_PIPER_URL", server.URL)
	t.Setenv("QUASAR_TTS_PIPER_DIR", dir)

	name, err := piperSpeech(t.Context(), "Согласно документам, ответ готов.")
	if err != nil {
		t.Fatal(err)
	}
	if gotText != "Согласно документам, ответ готов." {
		t.Fatalf("text sent to piper: %q", gotText)
	}
	info, err := os.Stat(filepath.Join(dir, name))
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() != int64(len(wav)) {
		t.Fatalf("saved %d bytes, want %d", info.Size(), len(wav))
	}
}

func TestPiperSpeechRejectsNonWav(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("not audio"))
	}))
	defer server.Close()
	t.Setenv("QUASAR_TTS_PIPER_URL", server.URL)
	t.Setenv("QUASAR_TTS_PIPER_DIR", t.TempDir())

	if _, err := piperSpeech(t.Context(), "текст"); err == nil {
		t.Fatal("non-WAV body must be rejected")
	}
}

func TestSpeakPiperQueuesLocalFile(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(testWAV())
	}))
	defer server.Close()
	t.Setenv("QUASAR_TTS_PIPER_URL", server.URL)
	t.Setenv("QUASAR_TTS_PIPER_DIR", t.TempDir())

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
	if len(directives) != 1 || directives[0].GetName() != "local_audio_file_play" {
		t.Fatalf("unexpected directives: %+v", directives)
	}
	var payload fileplayer.TAudioFilePlayerCapability_TLocalAudioFilePlayDirective
	if err := proto.Unmarshal(directives[0].GetPayloadRaw(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.GetFileName() == "" {
		t.Fatal("local file directive without a file name")
	}
}

func TestLocalFileDirectiveRejectsMixedFields(t *testing.T) {
	if _, err := makeSoundDirective(sound.Request{File: "piper.wav", URL: "http://example.com/a.mp3"}); err == nil {
		t.Fatal("file and URL must not be combined")
	}
	directive, err := makeSoundDirective(sound.Request{File: "piper.wav"})
	if err != nil {
		t.Fatal(err)
	}
	if directive.GetName() != "local_audio_file_play" {
		t.Fatalf("unexpected directive %q", directive.GetName())
	}
}
