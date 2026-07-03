package storage

import (
	"fmt"
	"time"
)

// S3Adapter provides screenshot upload and retrieval for VisAgent visual testing.
type S3Adapter struct {
	bucket   string
	region   string
	endpoint string
}

// NewS3Adapter creates a new S3Adapter with the given bucket configuration.
func NewS3Adapter(bucket, region, endpoint string) *S3Adapter {
	if region == "" {
		region = "us-east-1"
	}
	return &S3Adapter{
		bucket:   bucket,
		region:   region,
		endpoint: endpoint,
	}
}

// UploadScreenshot uploads screenshot data for the given testCaseID and returns
// the S3 object URL. This is a stub that returns a mock URL.
func (s *S3Adapter) UploadScreenshot(testCaseID string, data []byte) (string, error) {
	if testCaseID == "" {
		return "", fmt.Errorf("testCaseID must not be empty")
	}
	if len(data) == 0 {
		return "", fmt.Errorf("data must not be empty")
	}

	// Simulate upload latency
	time.Sleep(30 * time.Millisecond)

	// Generate a mock S3 object key
	timestamp := time.Now().UnixMilli()
	key := fmt.Sprintf("screenshots/%s/%d.png", testCaseID, timestamp)

	url := fmt.Sprintf("https://%s.s3.%s.amazonaws.com/%s", s.bucket, s.region, key)
	if s.endpoint != "" {
		url = fmt.Sprintf("%s/%s/%s", s.endpoint, s.bucket, key)
	}

	return url, nil
}

// GetScreenshotURL returns the expected S3 URL for a given testCaseID.
func (s *S3Adapter) GetScreenshotURL(testCaseID string) string {
	if s.endpoint != "" {
		return fmt.Sprintf("%s/%s/screenshots/%s", s.endpoint, s.bucket, testCaseID)
	}
	return fmt.Sprintf("https://%s.s3.%s.amazonaws.com/screenshots/%s", s.bucket, s.region, testCaseID)
}
