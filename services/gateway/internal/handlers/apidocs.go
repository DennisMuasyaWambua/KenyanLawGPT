package handlers

import (
	_ "embed"
	"net/http"

	"github.com/gin-gonic/gin"
)

//go:embed apidocs/openapi.json
var openAPISpec []byte

// Swagger UI loaded from a pinned CDN build; the spec is served by this gateway.
const swaggerHTML = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Advocatus API docs</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css"></head>
<body><div id="ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#ui",deepLinking:true,tryItOutEnabled:false});</script>
</body></html>`

// registerDocs serves public API documentation (no tenant, no auth).
func registerDocs(r *gin.Engine) {
	r.GET("/openapi.json", func(c *gin.Context) { c.Data(http.StatusOK, "application/json", openAPISpec) })
	r.GET("/docs", func(c *gin.Context) { c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(swaggerHTML)) })
}
