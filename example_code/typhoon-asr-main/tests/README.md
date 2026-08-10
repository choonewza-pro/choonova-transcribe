# Typhoon ASR Tests

This directory contains the test suite for the Typhoon ASR package.

## Test Structure

- `test_typhoon_asr.py` - Tests for the main `typhoon_asr` package functionality
- `test_cli.py` - Tests for the CLI script `typhoon_asr_inference.py`
- `conftest.py` - Shared pytest fixtures and configuration

## Running Tests

### Install Test Dependencies
```bash
pip install -r test-requirements.txt
```

### Run All Tests
```bash
pytest
```

### Run Specific Test Files
```bash
pytest tests/test_typhoon_asr.py
pytest tests/test_cli.py
```

### Run with Verbose Output
```bash
pytest -v
```

### Run Only Unit Tests
```bash
pytest -m unit
```

### Skip Slow Tests
```bash
pytest -m "not slow"
```

## Test Coverage

### Unit Tests
- Audio processing and validation
- Model loading with different device configurations
- Transcription functionality (basic and with timestamps)
- Error handling for edge cases
- File cleanup and temporary file management

### Integration Tests
- Full transcription pipeline with mocked model
- End-to-end CLI functionality
- Performance metrics (RTF calculation)

### Mock Strategy
Tests use comprehensive mocking to avoid downloading the actual Typhoon ASR model:
- `nemo_asr.models.ASRModel.from_pretrained` is mocked
- Audio processing is tested with real temporary files
- Model responses are simulated with predefined Thai text

## Test Data
- Temporary audio files are generated programmatically
- Thai text samples are provided as fixtures
- All temporary files are cleaned up automatically

## Adding New Tests

1. Add test functions to appropriate test files
2. Use existing fixtures where possible
3. Mock external dependencies (model loading, network calls)
4. Follow naming convention: `test_<functionality>`

## CI/CD Integration
The tests are designed to run in CI/CD environments:
- No external dependencies on real models
- Fast execution with mocking
- Self-contained test data generation
