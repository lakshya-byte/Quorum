package service

import (
	"context"
	"time"

	"patchloop-backend/internal/dto"
	"patchloop-backend/internal/models"
	// "patchloop-backend/internal/observability"
	"patchloop-backend/internal/pkg/hash"
	pkgjwt "patchloop-backend/internal/pkg/jwt"
	"patchloop-backend/internal/pkg/otp"
	"patchloop-backend/internal/pkg/random"
	"patchloop-backend/internal/repository"

	"go.mongodb.org/mongo-driver/v2/bson"
)

const (
	maxOTPAttempts    = 5
	otpResendCooldown = 60 * time.Second
	refreshTokenBytes = 32
)

type AuthService struct {
	users  *repository.UserRepository
	otps   *repository.OTPRepository
	tokens *repository.TokenRepository
	mailer *Mailer

	jwtAccessSecret  string
	jwtRefreshSecret string
	accessTTL        time.Duration
	refreshTTL       time.Duration
	otpTTL           time.Duration
}

type AuthServiceConfig struct {
	JWTAccessSecret  string
	JWTRefreshSecret string
	AccessTTLMin     int
	RefreshTTLDays   int
	OTPTTLMin        int
}

func NewAuthService(users *repository.UserRepository, otps *repository.OTPRepository, tokens *repository.TokenRepository, mailer *Mailer, cfg AuthServiceConfig) *AuthService {
	return &AuthService{
		users:            users,
		otps:             otps,
		tokens:           tokens,
		mailer:           mailer,
		jwtAccessSecret:  cfg.JWTAccessSecret,
		jwtRefreshSecret: cfg.JWTRefreshSecret,
		accessTTL:        time.Duration(cfg.AccessTTLMin) * time.Minute,
		refreshTTL:       time.Duration(cfg.RefreshTTLDays) * 24 * time.Hour,
		otpTTL:           time.Duration(cfg.OTPTTLMin) * time.Minute,
	}
}

// TokenPair holds the raw tokens to be set as cookies by the handler.
type TokenPair struct {
	AccessToken  string
	RefreshToken string
}

func (s *AuthService) Signup(ctx context.Context, req dto.SignupRequest) (*models.User, error) {
	passwordHash, err := hash.HashPassword(req.Password)
	if err != nil {
		return nil, err
	}

	user := &models.User{
		Email:         req.Email,
		PasswordHash:  passwordHash,
		CompanyName:   req.CompanyName,
		EmailVerified: true, // email verification disabled for now; set back to false to re-enable
	}

	if err := s.users.Create(ctx, user); err != nil {
		if err == repository.ErrDuplicateEmail {
			return nil, ErrEmailTaken
		}
		return nil, err
	}

	// if err := s.issueAndSendOTP(ctx, user); err != nil {
	// 	return nil, err
	// }

	return user, nil
}

func (s *AuthService) issueAndSendOTP(ctx context.Context, user *models.User) error {
	code, err := otp.Generate()
	if err != nil {
		return err
	}

	codeHash, err := hash.HashPassword(code)
	if err != nil {
		return err
	}

	// Clear any previous outstanding codes so only the newest is valid.
	if err := s.otps.DeleteAllForUser(ctx, user.ID, models.OTPPurposeSignupVerify); err != nil {
		return err
	}

	record := &models.OTP{
		UserID:    user.ID,
		CodeHash:  codeHash,
		Purpose:   models.OTPPurposeSignupVerify,
		ExpiresAt: time.Now().UTC().Add(s.otpTTL),
	}
	if err := s.otps.Create(ctx, record); err != nil {
		return err
	}

	// The OTP is persisted regardless of mail delivery, so a transient
	// provider failure doesn't strand the account — the user can retry via
	// resend-otp instead of losing the signup entirely.
	// if err := s.mailer.SendOTPEmail(user.Email, code); err != nil {
	// 	// Never log the email address; the user id is enough to correlate.
	// 	observability.L(ctx).Error("failed to send OTP email", "user_id", user.ID.Hex(), "error", err.Error())
	// }

	return nil
}

func (s *AuthService) ResendOTP(ctx context.Context, email string) error {
	user, err := s.users.FindByEmail(ctx, email)
	if err != nil {
		if err == repository.ErrNotFound {
			return ErrUserNotFound
		}
		return err
	}
	if user.EmailVerified {
		return nil // already verified, nothing to do — avoid leaking state to caller
	}

	existing, err := s.otps.LatestForUser(ctx, user.ID, models.OTPPurposeSignupVerify)
	if err == nil && time.Since(existing.CreatedAt) < otpResendCooldown {
		return ErrResendCooldown
	}
	if err != nil && err != repository.ErrNotFound {
		return err
	}

	return s.issueAndSendOTP(ctx, user)
}

func (s *AuthService) VerifyOTP(ctx context.Context, req dto.VerifyOTPRequest) (*models.User, *TokenPair, error) {
	user, err := s.users.FindByEmail(ctx, req.Email)
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, nil, ErrUserNotFound
		}
		return nil, nil, err
	}

	record, err := s.otps.LatestForUser(ctx, user.ID, models.OTPPurposeSignupVerify)
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, nil, ErrOTPExpired
		}
		return nil, nil, err
	}

	if record.Attempts >= maxOTPAttempts {
		return nil, nil, ErrTooManyOTPAttempts
	}

	if !hash.CheckPassword(req.Code, record.CodeHash) {
		_ = s.otps.IncrementAttempts(ctx, record.ID)
		return nil, nil, ErrInvalidOTP
	}

	if err := s.users.MarkEmailVerified(ctx, user.ID); err != nil {
		return nil, nil, err
	}
	_ = s.otps.DeleteByID(ctx, record.ID)
	user.EmailVerified = true

	pair, err := s.issueTokenPair(ctx, user)
	if err != nil {
		return nil, nil, err
	}

	return user, pair, nil
}

func (s *AuthService) Login(ctx context.Context, req dto.LoginRequest) (*models.User, *TokenPair, error) {
	user, err := s.users.FindByEmail(ctx, req.Email)
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, nil, ErrInvalidCredentials
		}
		return nil, nil, err
	}

	if !hash.CheckPassword(req.Password, user.PasswordHash) {
		return nil, nil, ErrInvalidCredentials
	}

	// if !user.EmailVerified {
	// 	return nil, nil, ErrEmailNotVerified
	// }

	pair, err := s.issueTokenPair(ctx, user)
	if err != nil {
		return nil, nil, err
	}

	return user, pair, nil
}

func (s *AuthService) issueTokenPair(ctx context.Context, user *models.User) (*TokenPair, error) {
	accessToken, err := pkgjwt.GenerateAccessToken(s.jwtAccessSecret, user.ID.Hex(), user.Email, s.accessTTL)
	if err != nil {
		return nil, err
	}

	rawRefresh, err := random.String(refreshTokenBytes)
	if err != nil {
		return nil, err
	}

	record := &models.RefreshToken{
		UserID:    user.ID,
		TokenHash: hash.HashToken(rawRefresh),
		Revoked:   false,
		ExpiresAt: time.Now().UTC().Add(s.refreshTTL),
	}
	if err := s.tokens.Create(ctx, record); err != nil {
		return nil, err
	}

	return &TokenPair{AccessToken: accessToken, RefreshToken: rawRefresh}, nil
}

func (s *AuthService) Refresh(ctx context.Context, rawRefreshToken string) (*TokenPair, error) {
	tokenHash := hash.HashToken(rawRefreshToken)

	record, err := s.tokens.FindValidByHash(ctx, tokenHash)
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, ErrInvalidRefreshToken
		}
		return nil, err
	}

	user, err := s.users.FindByID(ctx, record.UserID)
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, ErrUserNotFound
		}
		return nil, err
	}

	// Rotate: revoke the used token, issue a fresh pair.
	if err := s.tokens.Revoke(ctx, record.ID); err != nil {
		return nil, err
	}

	return s.issueTokenPair(ctx, user)
}

func (s *AuthService) Logout(ctx context.Context, rawRefreshToken string) error {
	if rawRefreshToken == "" {
		return nil
	}
	return s.tokens.RevokeByHash(ctx, hash.HashToken(rawRefreshToken))
}

func (s *AuthService) GetUserByID(ctx context.Context, id string) (*models.User, error) {
	objID, err := bson.ObjectIDFromHex(id)
	if err != nil {
		return nil, ErrUserNotFound
	}
	user, err := s.users.FindByID(ctx, objID)
	if err != nil {
		if err == repository.ErrNotFound {
			return nil, ErrUserNotFound
		}
		return nil, err
	}
	return user, nil
}
