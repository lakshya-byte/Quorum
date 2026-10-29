package dto

type CreateRunRequest struct {
	BugID  string `json:"bugId" binding:"required,max=64"`
	Engine string `json:"engine" binding:"omitempty,oneof=loop graph"`
	Replay bool   `json:"replay"`
}

type CreateRunResponse struct {
	RunID  string `json:"runId"`
	Mode   string `json:"mode"`
	Engine string `json:"engine"`
	Notice string `json:"notice,omitempty"`
}

type DemoRunRequest struct {
	BugID string `json:"bugId" binding:"required,max=64"`
}

type BugResponse struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Issue string `json:"issue"`
	Tier  any    `json:"tier,omitempty"`
}

type CreateTokenRequest struct {
	Name string `json:"name" binding:"required,min=1,max=100"`
}
