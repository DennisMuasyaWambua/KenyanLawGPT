package metrics

// Dependency-free Prometheus text-format metrics: request counts by status
// class, gRPC client errors, and reminder/ingestion job counters.

import (
	"fmt"
	"sort"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

var (
	mu       sync.Mutex
	counters = map[string]float64{}
	started  = time.Now()
)

func Inc(name string, labels map[string]string) {
	key := name
	if len(labels) > 0 {
		keys := make([]string, 0, len(labels))
		for k := range labels {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		key += "{"
		for i, k := range keys {
			if i > 0 {
				key += ","
			}
			key += k + "=" + strconv.Quote(labels[k])
		}
		key += "}"
	}
	mu.Lock()
	counters[key]++
	mu.Unlock()
}

// HTTP is a gin middleware counting requests by status class.
func HTTP() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Next()
		Inc("wakili_http_requests_total", map[string]string{
			"code":   strconv.Itoa(c.Writer.Status()),
			"method": c.Request.Method,
		})
	}
}

func Handler() gin.HandlerFunc {
	return func(c *gin.Context) {
		mu.Lock()
		defer mu.Unlock()
		c.Header("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprintf(c.Writer, "# TYPE wakili_uptime_seconds gauge\nwakili_uptime_seconds %f\n", time.Since(started).Seconds())
		keys := make([]string, 0, len(counters))
		for k := range counters {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			fmt.Fprintf(c.Writer, "%s %f\n", k, counters[k])
		}
	}
}
