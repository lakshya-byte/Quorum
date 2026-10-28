package dto

type SignupRequest struct {
	Email       string `json:"email" binding:"required,email"`
	Password    string `json:"password" binding:"required,min=8"`
	CompanyName string `json:"companyName" binding:"required,min=1,max=200"`
}

type LoginRequest struct {
	Email    string `json:"email" binding:"required,email"`
	Password string `json:"password" binding:"required"`
}

type VerifyOTPRequest struct {
	Email string `json:"email" binding:"required,email"`
	Code  string `json:"code" binding:"required,len=6,numeric"`
}

type ResendOTPRequest struct {
	Email string `json:"email" binding:"required,email"`
}

type UserResponse struct {
	ID            string `json:"id"`
	Email         string `json:"email"`
	CompanyName   string `json:"companyName"`
	EmailVerified bool   `json:"emailVerified"`
}
