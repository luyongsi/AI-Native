package middleware

import "net/http"

// Chain composes middleware in reverse order so they execute
// in the natural reading order: Chain(h, m1, m2, m3) => m1(m2(m3(h))).
func Chain(handler http.HandlerFunc, middlewares ...func(http.HandlerFunc) http.HandlerFunc) http.HandlerFunc {
	for i := len(middlewares) - 1; i >= 0; i-- {
		handler = middlewares[i](handler)
	}
	return handler
}
