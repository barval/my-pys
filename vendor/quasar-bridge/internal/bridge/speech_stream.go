package bridge

import (
	"html"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

var (
	reFencedCode   = regexp.MustCompile("(?s)```.*?```|~~~.*?~~~")
	reImage        = regexp.MustCompile(`!\[[^\]]*\]\([^)]*\)`)
	reInlineCode   = regexp.MustCompile("`+([^`]*)`+")
	reLink         = regexp.MustCompile(`\[([^\]]+)\]\([^)]*\)`)
	reRefLink      = regexp.MustCompile(`\[([^\]]+)\]\[[^\]]*\]`)
	reAutoLink     = regexp.MustCompile(`<https?://[^>]+>`)
	reBareURL      = regexp.MustCompile(`https?://\S+`)
	reBoldItalic   = regexp.MustCompile(`\*\*\*(.+?)\*\*\*`)
	reBold         = regexp.MustCompile(`\*\*(.+?)\*\*`)
	reItalic       = regexp.MustCompile(`\*(.+?)\*`)
	reUnderBold    = regexp.MustCompile(`(^|[^\p{L}\p{N}])__(.+?)__([^\p{L}\p{N}]|$)`)
	reUnderItalic  = regexp.MustCompile(`(^|[^\p{L}\p{N}])_(.+?)_([^\p{L}\p{N}]|$)`)
	reStrike       = regexp.MustCompile(`~~(.+?)~~`)
	reOrphanBefore = regexp.MustCompile(`([\p{L}])\*\*`)
	reOrphanAfter  = regexp.MustCompile(`\*\*([\p{L}])`)
	reHTMLTag      = regexp.MustCompile(`</?[^>]+>`)
	reHeading      = regexp.MustCompile(`(?m)^#{1,6}\s+`)
	reBlockquote   = regexp.MustCompile(`(?m)^>\s+`)
	reTask         = regexp.MustCompile(`(?m)^\s*[-*+]\s+\[[ xX]\]\s+`)
	reUnordered    = regexp.MustCompile(`(?m)^\s*[-*+]\s+`)
	reOrdered      = regexp.MustCompile(`(?m)^\s*\d+[.)]\s+`)
	reThematic     = regexp.MustCompile(`(?m)^\s*[-*_]{3,}\s*$`)
	reTableSep     = regexp.MustCompile(`(?m)^\s*\|?[\s:|-]+\|?\s*$`)
	reTablePipe    = regexp.MustCompile(`\|`)
	reSpaces       = regexp.MustCompile(`[ \t]+`)
	reNewlines     = regexp.MustCompile(`\n{3,}`)
	reAbbreviation = regexp.MustCompile(`(?i)(?:^|[\s(])(?:г|т|д|ул|пр|пер|кв|ж|корп|стр|оф|тел|факс|напр|т\.?е|т\.?д|и\.?т\.?д|и\.?т\.?п|e\.?g|i\.?e|см|рис|табл)\.$`)
)

// cleanSpeechText strips Markdown and UI noise before TTS. It intentionally
// keeps the text of links and inline code, and drops fenced code, images and
// bare URLs that would be unreadable aloud.
func cleanSpeechText(text string) string {
	if strings.TrimSpace(text) == "" {
		return ""
	}
	text = reFencedCode.ReplaceAllString(text, " ")
	text = reImage.ReplaceAllString(text, " ")
	text = reInlineCode.ReplaceAllString(text, "$1")
	text = reLink.ReplaceAllString(text, "$1")
	text = reRefLink.ReplaceAllString(text, "$1")
	text = reAutoLink.ReplaceAllString(text, " ")
	text = reBareURL.ReplaceAllString(text, " ")
	text = reBoldItalic.ReplaceAllString(text, "$1")
	text = reBold.ReplaceAllString(text, "$1")
	text = reItalic.ReplaceAllString(text, "$1")
	text = reUnderBold.ReplaceAllString(text, "$1$2$3")
	text = reUnderItalic.ReplaceAllString(text, "$1$2$3")
	text = reStrike.ReplaceAllString(text, "$1")
	text = reOrphanBefore.ReplaceAllString(text, "$1")
	text = reOrphanAfter.ReplaceAllString(text, "$1")
	text = reHTMLTag.ReplaceAllString(text, " ")
	text = html.UnescapeString(text)
	text = reHeading.ReplaceAllString(text, "")
	text = reBlockquote.ReplaceAllString(text, "")
	text = reTask.ReplaceAllString(text, "")
	text = reUnordered.ReplaceAllString(text, "")
	text = reOrdered.ReplaceAllString(text, "")
	text = reThematic.ReplaceAllString(text, "")
	text = reTableSep.ReplaceAllString(text, "")
	text = reTablePipe.ReplaceAllString(text, ", ")
	text = reSpaces.ReplaceAllString(text, " ")
	text = reNewlines.ReplaceAllString(text, "\n\n")
	return strings.TrimSpace(text)
}

type streamBuffer struct {
	pending  string
	maxChars int
	index    int
}

func newStreamBuffer(maxChars int) *streamBuffer {
	if maxChars < 1 {
		maxChars = defaultSpeechChunkChars
	}
	return &streamBuffer{maxChars: maxChars}
}

// Add appends an LLM delta and returns complete, cleaned speech chunks. Chunks
// are cut only at sentence boundaries: the first chunk is exactly one sentence,
// later sentences are merged up to the growing target size.
func (b *streamBuffer) Add(delta string) []string {
	b.pending += delta
	var out []string
	for {
		cut := safeSentenceCut(b.pending)
		if cut > 0 {
			runes := len([]rune(b.pending[:cut]))
			if runes > b.maxChars {
				// Предложение длиннее лимита: режем по словам, иначе кусок
				// не влезет в TTS-запрос.
				cut = lastSpaceCut(b.pending, b.maxChars)
			} else if b.index > 0 && runes < speechChunkTarget(b.index, b.maxChars) {
				// Копим короткие предложения до целевого размера куска.
				if len([]rune(b.pending)) <= b.maxChars*2 {
					break
				}
				cut = lastSpaceCut(b.pending, b.maxChars)
			}
		} else if len([]rune(b.pending)) > b.maxChars*2 {
			// Предложение ещё не закончилось, но текста уже слишком много.
			cut = lastSpaceCut(b.pending, b.maxChars)
		}
		if cut <= 0 {
			break
		}
		part := strings.TrimSpace(b.pending[:cut])
		b.pending = b.pending[cut:]
		if clean := cleanSpeechText(part); clean != "" {
			chunks := splitSpeech(clean, b.maxChars, 100)
			out = append(out, chunks...)
			b.index += len(chunks)
		}
	}
	return out
}

// Flush returns the rest of the answer, merging short sentences.
func (b *streamBuffer) Flush() []string {
	part := strings.TrimSpace(b.pending)
	b.pending = ""
	if part == "" {
		return nil
	}
	clean := cleanSpeechText(part)
	if clean == "" {
		return nil
	}
	chunks := splitSpeechAdaptive(clean, b.maxChars, 100)
	b.index += len(chunks)
	return chunks
}

// safeSentenceCut returns the byte index after the last complete sentence.
// It requires whitespace (or end of text) after punctuation, so decimals and
// URLs such as 3.14 and example.com are not split. Closing quotes and brackets
// are allowed before the whitespace.
func safeSentenceCut(text string) int {
	for i := 0; i < len(text); {
		r, size := utf8.DecodeRuneInString(text[i:])
		if r != '.' && r != '!' && r != '?' && r != '…' {
			i += size
			continue
		}
		end := i + size
		j := end
		for j < len(text) {
			rr, ss := utf8.DecodeRuneInString(text[j:])
			if strings.ContainsRune("»”\"')\\]}", rr) {
				j += ss
				continue
			}
			break
		}
		boundary := j == len(text)
		if !boundary {
			rr, _ := utf8.DecodeRuneInString(text[j:])
			boundary = unicode.IsSpace(rr)
		}
		if boundary && r == '.' && (isDecimalPoint(text, i) || abbreviationBefore(text, end)) {
			i = end
			continue
		}
		if boundary {
			k := j
			for k < len(text) {
				rr, ss := utf8.DecodeRuneInString(text[k:])
				if !unicode.IsSpace(rr) {
					break
				}
				k += ss
			}
			return k
		}
		i = end
	}
	return 0
}

func isDecimalPoint(text string, dot int) bool {
	before, _ := utf8.DecodeLastRuneInString(text[:dot])
	after, _ := utf8.DecodeRuneInString(text[dot+1:])
	return unicode.IsDigit(before) || unicode.IsDigit(after)
}

func abbreviationBefore(text string, end int) bool {
	return reAbbreviation.MatchString(text[:end])
}

func lastSpaceCut(text string, maxChars int) int {
	limit := 0
	runes := 0
	lastSpace := -1
	for i := 0; i < len(text) && runes < maxChars; {
		r, size := utf8.DecodeRuneInString(text[i:])
		if unicode.IsSpace(r) {
			lastSpace = i
		}
		i += size
		runes++
		limit = i
	}
	if lastSpace > 0 {
		return lastSpace
	}
	return limit
}
