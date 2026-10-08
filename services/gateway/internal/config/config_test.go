package config

import "testing"

func TestIsLocalEndpoint(t *testing.T) {
	for ep, want := range map[string]bool{
		"": true, "localhost:59000": true, "127.0.0.1:9000": true, "minio:9000": true,
		"files.example.com": false, "abc.r2.cloudflarestorage.com": false,
	} {
		if got := isLocalEndpoint(ep); got != want {
			t.Errorf("isLocalEndpoint(%q) = %v, want %v", ep, got, want)
		}
	}
}

func TestDefaultATBaseURL(t *testing.T) {
	if defaultATBaseURL("sandbox") != "https://api.sandbox.africastalking.com" || defaultATBaseURL("") != "https://api.sandbox.africastalking.com" {
		t.Error("sandbox/empty username should use the sandbox host")
	}
	if defaultATBaseURL("mycompany") != "https://api.africastalking.com" {
		t.Error("a real username must use the production host")
	}
}
