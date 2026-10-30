package render

import "fmt"

// outcomeHead is the bold verdict line start. Legacy bug-fix streams keep the
// SOLVED / NOT SOLVED wording; swarm runs say COMPLETE / FAILED.
func (r *Renderer) outcomeHead(outcome string, swarm bool) string {
	switch outcome {
	case "complete":
		if swarm {
			return r.c(bold+green, "✓ COMPLETE")
		}
		return r.c(bold+green, "✓ SOLVED")
	case "partial":
		return r.c(bold+amber, "◐ PARTIAL")
	case "needs_input":
		return r.c(bold+amber, "? NEEDS INPUT")
	case "blocked":
		return r.c(bold+red, "⊘ BLOCKED")
	}
	if swarm {
		return r.c(bold+red, "✗ FAILED")
	}
	return r.c(bold+red, "✗ NOT SOLVED")
}

func (r *Renderer) gatesText(has bool) string {
	if !has {
		return ""
	}
	col := green
	if r.HardPass < r.HardTotal {
		col = red
	}
	return "  " + r.c(col, fmt.Sprintf("%d/%d hard gates pass", r.HardPass, r.HardTotal))
}

func advisoryText(a map[string]any) string {
	id := str(a["criterion_id"])
	if id == "" {
		id = str(a["id"])
	}
	s := id
	if sc, ok := a["score"].(float64); ok {
		s += fmt.Sprintf(" %.2f", sc)
	}
	d := str(a["detail"])
	if d == "" {
		d = str(a["rationale"])
	}
	if d != "" {
		s += ": " + truncRunes(d, 120)
	}
	return s
}
