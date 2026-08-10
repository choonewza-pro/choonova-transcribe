import pytest
import os
import tempfile
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'packages', 'typhoon_asr'))

from typhoon_asr import transcribe


class TestTyphoonASR:
    """Test suite for Typhoon ASR package"""

    @pytest.fixture
    def sample_audio_file(self):
        """Create a temporary audio file for testing"""
        # Generate a simple sine wave audio file
        sample_rate = 16000
        duration = 1.0  # 1 second
        frequency = 440  # A4 note
        
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio_data = np.sin(frequency * t * 2 * np.pi) * 0.3
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            import soundfile as sf
            sf.write(f.name, audio_data, sample_rate)
            yield f.name
        
        # Cleanup
        if os.path.exists(f.name):
            os.remove(f.name)
    
    @pytest.fixture
    def mock_model(self):
        """Mock ASR model for testing"""
        model = Mock()
        model.transcribe.return_value = ["สวัสดี นี่คือการทดสอบ"]
        return model
    
    @pytest.fixture
    def mock_model_with_timestamps(self):
        """Mock ASR model with timestamp hypotheses for testing"""
        model = Mock()
        
        # Create mock hypothesis object
        mock_hypothesis = Mock()
        mock_hypothesis.text = "สวัสดี นี่คือการทดสอบ"
        
        model.transcribe.return_value = [mock_hypothesis]
        return model

    def test_transcribe_basic(self, sample_audio_file, mock_model):
        """Test basic transcription functionality"""
        with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model):
            result = transcribe(sample_audio_file)
            
            assert 'text' in result
            assert 'processing_time' in result
            assert 'audio_duration' in result
            assert result['text'] == "สวัสดี นี่คือการทดสอบ"
            assert isinstance(result['processing_time'], float)
            assert isinstance(result['audio_duration'], float)
            assert 'timestamps' not in result

    def test_transcribe_with_timestamps(self, sample_audio_file, mock_model_with_timestamps):
        """Test transcription with timestamps"""
        with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model_with_timestamps):
            result = transcribe(sample_audio_file, with_timestamps=True)
            
            assert 'text' in result
            assert 'timestamps' in result
            assert 'processing_time' in result
            assert 'audio_duration' in result
            
            assert result['text'] == "สวัสดี นี่คือการทดสอบ"
            assert isinstance(result['timestamps'], list)
            assert len(result['timestamps']) > 0
            
            # Check timestamp structure
            timestamp = result['timestamps'][0]
            assert 'word' in timestamp
            assert 'start' in timestamp
            assert 'end' in timestamp
            assert isinstance(timestamp['start'], float)
            assert isinstance(timestamp['end'], float)

    def test_transcribe_file_not_found(self):
        """Test handling of non-existent file"""
        with pytest.raises(FileNotFoundError, match="File not found"):
            transcribe("nonexistent_file.wav")

    def test_transcribe_unsupported_format(self):
        """Test handling of unsupported audio format"""
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b"not audio")
            temp_file = f.name
        
        try:
            with pytest.raises(ValueError, match="Unsupported format"):
                transcribe(temp_file)
        finally:
            os.remove(temp_file)

    def test_transcribe_audio_loading_failure(self):
        """Test handling of audio loading failure"""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            temp_file = f.name
        
        try:
            with patch('typhoon_asr.librosa.load', return_value=(None, 16000)):
                with pytest.raises(IOError, match="Failed to load audio file"):
                    transcribe(temp_file)
        finally:
            os.remove(temp_file)

    def test_transcribe_model_loading_failure(self, sample_audio_file):
        """Test handling of model loading failure"""
        with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=None):
            with pytest.raises(RuntimeError, match="Failed to load the ASR model"):
                transcribe(sample_audio_file)

    def test_transcribe_device_auto_cpu(self, sample_audio_file, mock_model):
        """Test device auto-selection when CUDA is not available"""
        with patch('typhoon_asr.torch.cuda.is_available', return_value=False):
            with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model) as mock_load:
                transcribe(sample_audio_file, device='auto')
                
                # Verify model was loaded with CPU
                mock_load.assert_called_once_with(
                    model_name="scb10x/typhoon-asr-realtime",
                    map_location='cpu'
                )

    def test_transcribe_device_auto_cuda(self, sample_audio_file, mock_model):
        """Test device auto-selection when CUDA is available"""
        with patch('typhoon_asr.torch.cuda.is_available', return_value=True):
            with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model) as mock_load:
                transcribe(sample_audio_file, device='auto')
                
                # Verify model was loaded with CUDA
                mock_load.assert_called_once_with(
                    model_name="scb10x/typhoon-asr-realtime",
                    map_location='cuda'
                )

    def test_transcribe_device_specified(self, sample_audio_file, mock_model):
        """Test explicit device specification"""
        with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model) as mock_load:
            transcribe(sample_audio_file, device='cpu')
            
            # Verify model was loaded with specified device
            mock_load.assert_called_once_with(
                model_name="scb10x/typhoon-asr-realtime",
                map_location='cpu'
            )

    def test_transcribe_custom_model_name(self, sample_audio_file, mock_model):
        """Test custom model name"""
        custom_model = "custom/model-name"
        with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model) as mock_load:
            transcribe(sample_audio_file, model_name=custom_model)
            
            # Verify custom model name was used
            mock_load.assert_called_once_with(
                model_name=custom_model,
                map_location='cpu'  # Default when CUDA not available
            )

    def test_transcribe_empty_transcription(self, sample_audio_file):
        """Test handling of empty transcription result"""
        mock_model = Mock()
        mock_model.transcribe.return_value = [""]
        
        with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model):
            result = transcribe(sample_audio_file)
            
            assert result['text'] == ""
            assert result['processing_time'] >= 0

    def test_transcribe_cleanup_temporary_file(self, sample_audio_file, mock_model):
        """Test that temporary processed files are cleaned up"""
        with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model):
            transcribe(sample_audio_file)
            
            # Check that processed file was cleaned up
            processed_file = f"processed_{Path(sample_audio_file).stem}.wav"
            assert not os.path.exists(processed_file)

    @pytest.mark.parametrize("audio_format", ['.wav', '.mp3', '.flac', '.ogg'])
    def test_transcribe_supported_formats(self, audio_format, mock_model):
        """Test that all supported audio formats are accepted"""
        with tempfile.NamedTemporaryFile(suffix=audio_format, delete=False) as f:
            # Write minimal audio data
            sample_rate = 16000
            audio_data = np.zeros(16000)  # 1 second of silence
            import soundfile as sf
            sf.write(f.name, audio_data, sample_rate)
            temp_file = f.name
        
        try:
            with patch('typhoon_asr.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model):
                # Should not raise an exception
                result = transcribe(temp_file)
                assert 'text' in result
        finally:
            os.remove(temp_file)
