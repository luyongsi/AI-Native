-- 011_test_case_validation.sql
-- Extend test_cases table with validation and augmentation support

-- Add new columns to test_cases if they don't exist
ALTER TABLE test_cases
ADD COLUMN IF NOT EXISTS validation_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS validation_errors JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS coverage_info JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual',
ADD COLUMN IF NOT EXISTS augmentation_suggestions JSONB DEFAULT NULL;

-- Create index for validation status queries
CREATE INDEX IF NOT EXISTS idx_test_cases_validation_status
    ON test_cases(validation_status);

-- Create index for source queries (for filtering AI-generated vs manual)
CREATE INDEX IF NOT EXISTS idx_test_cases_source
    ON test_cases(source);

-- Create index for composite queries
CREATE INDEX IF NOT EXISTS idx_test_cases_req_validation
    ON test_cases(req_id, validation_status);

-- Add comments for documentation
COMMENT ON COLUMN test_cases.validation_status IS 'Validation state: pending, passed, failed';
COMMENT ON COLUMN test_cases.validation_errors IS 'JSONB array of validation error details';
COMMENT ON COLUMN test_cases.coverage_info IS 'JSONB object containing coverage metrics';
COMMENT ON COLUMN test_cases.source IS 'Origin of test case: manual, a7_generated, a11_generated';
COMMENT ON COLUMN test_cases.augmentation_suggestions IS 'JSONB array of augmentation suggestions from A11';
