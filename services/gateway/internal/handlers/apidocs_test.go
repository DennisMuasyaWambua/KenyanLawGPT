package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestDocsServed(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	registerDocs(r)
	for _, p := range []string{"/docs", "/openapi.json"} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, p, nil))
		if w.Code != 200 {
			t.Fatalf("%s: %d", p, w.Code)
		}
	}
	var spec map[string]any
	if err := json.Unmarshal(openAPISpec, &spec); err != nil || spec["openapi"] == nil {
		t.Fatalf("invalid spec: %v", err)
	}
}
