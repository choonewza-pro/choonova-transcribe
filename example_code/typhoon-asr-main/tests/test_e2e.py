import pytest
import os
import sys
from pathlib import Path

# Add the package path to import typhoon_asr
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'packages', 'typhoon_asr'))

from typhoon_asr import transcribe


class TestEndToEnd:
    """End-to-end tests using real audio files and model"""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_transcribe_cv_test_wav_basic(self):
        """Test end-to-end transcription with cv_test.wav file"""
        # Path to the example audio file
        audio_file = os.path.join(os.path.dirname(__file__), '..', 'examples', 'cv_test.wav')
        
        # Verify the file exists
        assert os.path.exists(audio_file), f"Test audio file not found: {audio_file}"
        
        # Run transcription with real model
        result = transcribe(audio_file, device='cpu')
        
        # Verify result structure
        assert 'text' in result
        assert 'processing_time' in result
        assert 'audio_duration' in result
        
        # The text should be a string (extracted from Hypothesis object by the package)
        actual_text = result['text']
        if hasattr(actual_text, 'text'):
            # If it's still a Hypothesis object, extract the text
            actual_text = actual_text.text
        
        assert isinstance(actual_text, str)
        assert isinstance(result['processing_time'], float)
        assert isinstance(result['audio_duration'], float)
        assert result['processing_time'] > 0
        assert result['audio_duration'] > 0
        
        # Verify the expected transcription
        expected_text = "และหลังจากนั้นเป็นเวลานานเธอจึงสั่งซื้อผลิตภัณฑ์อีกอัน"
        assert actual_text == expected_text, f"Expected '{expected_text}', got '{actual_text}'"

    @pytest.mark.slow
    @pytest.mark.integration
    def test_transcribe_cv_test_wav_with_timestamps(self):
        """Test end-to-end transcription with timestamps using cv_test.wav file"""
        audio_file = os.path.join(os.path.dirname(__file__), '..', 'examples', 'cv_test.wav')
        
        # Verify the file exists
        assert os.path.exists(audio_file), f"Test audio file not found: {audio_file}"
        
        # Run transcription with timestamps
        result = transcribe(audio_file, with_timestamps=True, device='cpu')
        
        # Verify result structure
        assert 'text' in result
        assert 'timestamps' in result
        assert 'processing_time' in result
        assert 'audio_duration' in result
        
        # Extract text from Hypothesis object if needed
        actual_text = result['text']
        if hasattr(actual_text, 'text'):
            actual_text = actual_text.text
        
        # Verify the expected transcription
        expected_text = "และหลังจากนั้นเป็นเวลานานเธอจึงสั่งซื้อผลิตภัณฑ์อีกอัน"
        assert actual_text == expected_text, f"Expected '{expected_text}', got '{actual_text}'"
        
        # Verify timestamps structure
        assert isinstance(result['timestamps'], list)
        assert len(result['timestamps']) > 0
        
        # Check timestamp format
        for timestamp in result['timestamps']:
            assert 'word' in timestamp
            assert 'start' in timestamp
            assert 'end' in timestamp
            assert isinstance(timestamp['word'], str)
            assert isinstance(timestamp['start'], (int, float))
            assert isinstance(timestamp['end'], (int, float))
            assert timestamp['start'] >= 0
            assert timestamp['end'] >= timestamp['start']
        
        # Verify timestamps cover the full audio duration
        if result['timestamps']:
            last_timestamp = result['timestamps'][-1]
            assert last_timestamp['end'] <= result['audio_duration'] + 0.1  # Allow small tolerance

    @pytest.mark.slow
    @pytest.mark.integration
    def test_transcribe_cv_test_wav_performance_metrics(self):
        """Test performance metrics for cv_test.wav transcription"""
        audio_file = os.path.join(os.path.dirname(__file__), '..', 'examples', 'cv_test.wav')
        
        # Run transcription
        result = transcribe(audio_file, device='cpu')
        
        # Calculate RTF (Real-Time Factor)
        rtf = result['processing_time'] / result['audio_duration']
        
        # Verify reasonable performance (should complete in reasonable time)
        assert rtf < 10.0, f"RTF too high: {rtf:.3f}x (processing: {result['processing_time']:.2f}s, audio: {result['audio_duration']:.2f}s)"
        
        # Verify audio duration is reasonable (not zero, not extremely long)
        assert 1.0 <= result['audio_duration'] <= 60.0, f"Unexpected audio duration: {result['audio_duration']:.2f}s"
        
        # Verify processing time is reasonable
        assert 0.1 <= result['processing_time'] <= 300.0, f"Unexpected processing time: {result['processing_time']:.2f}s"
