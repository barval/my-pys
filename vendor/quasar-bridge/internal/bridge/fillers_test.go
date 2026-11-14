package bridge

import (
	"context"
	"testing"
	"time"

	"github.com/coder/websocket"
	"quasarbridge/internal/wire"
)

func testNative(t *testing.T) (*Native, <-chan wire.Frame) {
	t.Helper()
	down := make(chan wire.Frame, 8)
	n := NewNative(t.Context(),
		func(context.Context, websocket.MessageType, []byte) error { return nil },
		func(_ context.Context, _ websocket.MessageType, b []byte) error {
			down <- wire.Decode(b, wire.ServerToClient)
			return nil
		},
		delayedRoute{})
	t.Cleanup(n.Close)
	return n, down
}

func TestClearFillersClosesActiveFillerStream(t *testing.T) {
	n, down := testNative(t)
	p := &nativeRequest{
		ctx:                t.Context(),
		id:                 "filler-request",
		ttsID:              "filler-tts",
		speechActive:       true,
		speechActiveFiller: true,
		fillerStream:       12,
		fillerSent:         time.Now(),
	}

	n.clearFillers(p)

	select {
	case frame := <-down:
		control := frame.Server.GetStreamControl()
		if control == nil || control.GetClose() == nil {
			t.Fatalf("expected a stream close, got %s", frame.Kind())
		}
		if control.GetStreamId() != 12 || control.GetMessageId() != "filler-tts" {
			t.Fatalf("close targets stream %d message %q", control.GetStreamId(), control.GetMessageId())
		}
	case <-time.After(time.Second):
		t.Fatal("filler stream was not closed")
	}

	if !p.fillersStopped {
		t.Fatal("fillers must stay stopped after the answer arrives")
	}
	if p.fillerStream != 0 {
		t.Fatalf("filler stream must be forgotten, got %d", p.fillerStream)
	}
}

func TestClearFillersDropsQueuedFillersKeepsAnswer(t *testing.T) {
	n, down := testNative(t)
	p := &nativeRequest{
		ctx:   t.Context(),
		id:    "filler-request",
		ttsID: "answer-tts",
		speechQueue: []speechItem{
			{text: "Пока думаю.", filler: true},
			{text: "Первый кусок ответа.", filler: false},
			{text: "Ещё немного.", filler: true},
		},
	}

	n.clearFillers(p)

	if len(p.speechQueue) != 1 || p.speechQueue[0].filler {
		t.Fatalf("queued fillers were not dropped: %+v", p.speechQueue)
	}
	select {
	case frame := <-down:
		t.Fatalf("no frame expected without an active filler, got %s", frame.Kind())
	default:
	}
}

func TestFillerIdleOnlyWhenNothingIsSpoken(t *testing.T) {
	n, _ := testNative(t)
	p := &nativeRequest{ctx: t.Context(), id: "filler-request"}

	if !n.fillerIdle(p) {
		t.Fatal("idle request must accept a filler")
	}
	p.speechActive = true
	if n.fillerIdle(p) {
		t.Fatal("filler must not be sent while another speech item is active")
	}
	p.speechActive = false
	p.speechQueue = []speechItem{{text: "Пока думаю.", filler: true}}
	if n.fillerIdle(p) {
		t.Fatal("filler must not be sent while the queue is not empty")
	}
	p.speechQueue = nil
	p.fillersStopped = true
	if n.fillerIdle(p) {
		t.Fatal("filler must not be sent after the answer arrived")
	}
}

func TestClearFillersIgnoresStaleFillerStream(t *testing.T) {
	n, down := testNative(t)
	p := &nativeRequest{
		ctx:          t.Context(),
		id:           "filler-request",
		ttsID:        "filler-tts",
		fillerStream: 12,
		fillerSent:   time.Now().Add(-30 * time.Second),
	}

	n.clearFillers(p)

	select {
	case frame := <-down:
		t.Fatalf("stale filler stream must not be closed: %s", frame.Kind())
	default:
	}
}
