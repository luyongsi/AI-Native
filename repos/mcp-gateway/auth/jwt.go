package auth

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Claims represents the JWT claims for an agent-scoped token.
type Claims struct {
	jwt.RegisteredClaims
	AgentID string `json:"agent_id"`
	ReqID   string `json:"req_id"`
	TaskID  string `json:"task_id"`
}

// JWTAuth handles JWT signing and verification.
type JWTAuth struct {
	privateKey *rsa.PrivateKey
	publicKey  *rsa.PublicKey
}

// NewJWTAuth creates a JWTAuth with auto-generated temporary key pair.
func NewJWTAuth() *JWTAuth {
	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		log.Fatalf("Failed to generate RSA key pair: %v", err)
	}

	return &JWTAuth{
		privateKey: privateKey,
		publicKey:  &privateKey.PublicKey,
	}
}

// NewJWTAuthFromFiles loads keys from PEM files, falling back to generated keys.
func NewJWTAuthFromFiles(privPath, pubPath string) *JWTAuth {
	ja := &JWTAuth{}

	privData, err := os.ReadFile(privPath)
	if err != nil {
		log.Printf("WARN: Cannot read private key %s, generating temporary key: %v", privPath, err)
		return NewJWTAuth()
	}

	block, _ := pem.Decode(privData)
	if block == nil {
		log.Printf("WARN: Invalid PEM in %s, generating temporary key", privPath)
		return NewJWTAuth()
	}

	privKey, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		// Try PKCS1
		privKey, err = x509.ParsePKCS1PrivateKey(block.Bytes)
		if err != nil {
			log.Printf("WARN: Cannot parse private key %s, generating temporary key: %v", privPath, err)
			return NewJWTAuth()
		}
	}

	rsaKey, ok := privKey.(*rsa.PrivateKey)
	if !ok {
		log.Printf("WARN: Key in %s is not RSA, generating temporary key", privPath)
		return NewJWTAuth()
	}
	ja.privateKey = rsaKey

	if pubPath != "" {
		pubData, err := os.ReadFile(pubPath)
		if err == nil {
			block, _ := pem.Decode(pubData)
			if block != nil {
				pubKey, err := x509.ParsePKIXPublicKey(block.Bytes)
				if err == nil {
					if rsaPub, ok := pubKey.(*rsa.PublicKey); ok {
						ja.publicKey = rsaPub
					}
				}
			}
		}
	}

	if ja.publicKey == nil {
		ja.publicKey = &ja.privateKey.PublicKey
	}

	return ja
}

// IssueToken creates a new JWT for the given agent.
func (ja *JWTAuth) IssueToken(agentID, reqID, taskID string, ttl time.Duration) (string, error) {
	if ttl == 0 {
		ttl = 1 * time.Hour
	}

	now := time.Now().UTC()
	claims := &Claims{
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    "mcp-gateway",
			Subject:   agentID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
			ID:        fmt.Sprintf("%d", now.UnixNano()),
		},
		AgentID: agentID,
		ReqID:   reqID,
		TaskID:  taskID,
	}

	token := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	return token.SignedString(ja.privateKey)
}

// Verify is an HTTP middleware that rejects requests without a valid JWT.
func (ja *JWTAuth) Verify(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" {
			writeAuthError(w, "missing Authorization header")
			return
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			writeAuthError(w, "invalid Authorization header format")
			return
		}

		tokenStr := parts[1]
		claims := &Claims{}

		token, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (interface{}, error) {
			if _, ok := t.Method.(*jwt.SigningMethodRSA); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
			}
			return ja.publicKey, nil
		})

		if err != nil || !token.Valid {
			writeAuthError(w, fmt.Sprintf("invalid or expired token: %v", err))
			return
		}

		// Inject claims into request context for downstream handlers.
		r.Header.Set("X-Agent-ID", claims.AgentID)
		r.Header.Set("X-Req-ID", claims.ReqID)
		r.Header.Set("X-Task-ID", claims.TaskID)

		next(w, r)
	}
}

// HandleIssueToken is the HTTP handler for POST /auth/token.
func (ja *JWTAuth) HandleIssueToken(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var body struct {
		AgentID string `json:"agent_id"`
		ReqID   string `json:"req_id"`
		TaskID  string `json:"task_id"`
		TTL     int    `json:"ttl_seconds"`
	}

	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	if body.AgentID == "" {
		http.Error(w, `{"error":"agent_id is required"}`, http.StatusBadRequest)
		return
	}

	ttl := time.Duration(body.TTL) * time.Second
	if ttl <= 0 {
		ttl = 1 * time.Hour
	}

	token, err := ja.IssueToken(body.AgentID, body.ReqID, body.TaskID, ttl)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"error":"%v"}`, err), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"token":    token,
		"agent_id": body.AgentID,
	})
}

func writeAuthError(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	json.NewEncoder(w).Encode(map[string]string{
		"error": msg,
	})
}
