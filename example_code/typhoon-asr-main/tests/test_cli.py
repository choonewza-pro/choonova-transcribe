import pytest
import os
import sys
import tempfile
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import argparse

# Add the root directory to sys.path to import the CLI script
sys.path.insert(0, os.path.dirname(__file__))

# Import the CLI script as a module
import typhoon_asr_inference


class TestTyphoonASRCLI:
    """Test suite for Typhoon ASR CLI script"""

    @pytest.fixture
    def sample_audio_file(self):
        """Create a temporary audio file for testing"""
        sample_rate = 16000
        duration = 1.0
        frequency = 440
        
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio_data = np.sin(frequency * t * 2 * np.pi) * 0.3
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            import soundfile as sf
            sf.write(f.name, audio_data, sample_rate)
            yield f.name
        
        if os.path.exists(f.name):
            os.remove(f.name)

    @pytest.fixture
    def mock_model(self):
        """Mock ASR model for testing"""
        model = Mock()
        model.transcribe.return_value = ["สวัสดี นี่คือการทดสอบ"]
        return model

    @pytest.fixture
    def mock_model_with_hypotheses(self):
        """Mock ASR model with hypotheses for timestamp testing"""
        model = Mock()
        mock_hypothesis = Mock()
        mock_hypothesis.text = "สวัสดี นี่คือการทดสอบ"
        model.transcribe.return_value = [mock_hypothesis]
        return model

    def test_prepare_audio_success(self, sample_audio_file):
        """Test successful audio preparation"""
        success, output_path, info = typhoon_asr_inference.prepare_audio(sample_audio_file)
        
        assert success is True
        assert output_path is not None
        assert output_path.startswith("processed_")
        assert "original_sr" in info
        assert "target_sr" in info
        assert "duration" in info
        assert info["target_sr"] == 16000
        
        # Cleanup
        if os.path.exists(output_path):
            os.remove(output_path)

    def test_prepare_audio_file_not_found(self):
        """Test prepare_audio with non-existent file"""
        success, output_path, info = typhoon_asr_inference.prepare_audio("nonexistent.wav")
        
        assert success is False
        assert output_path is None
        assert "error" in info
        assert "File not found" in info["error"]

    def test_prepare_audio_unsupported_format(self):
        """Test prepare_audio with unsupported format"""
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b"not audio")
            temp_file = f.name
        
        try:
            success, output_path, info = typhoon_asr_inference.prepare_audio(temp_file)
            
            assert success is False
            assert output_path is None
            assert "error" in info
            assert "Unsupported format" in info["error"]
        finally:
            os.remove(temp_file)

    def test_prepare_audio_loading_failure(self):
        """Test prepare_audio with audio loading failure"""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            temp_file = f.name
        
        try:
            with patch('typhoon_asr_inference.librosa.load', return_value=(None, 16000)):
                success, output_path, info = typhoon_asr_inference.prepare_audio(temp_file)
                
                assert success is False
                assert output_path is None
                assert "error" in info
                assert "Failed to load audio file" in info["error"]
        finally:
            os.remove(temp_file)

    def test_load_typhoon_model_success(self, mock_model):
        """Test successful model loading"""
        with patch('typhoon_asr_inference.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model):
            model = typhoon_asr_inference.load_typhoon_model('cpu')
            
            assert model is not None
            assert model == mock_model

    def test_load_typhoon_model_failure(self):
        """Test model loading failure"""
        with patch('typhoon_asr_inference.nemo_asr.models.ASRModel.from_pretrained', return_value=None):
            model = typhoon_asr_inference.load_typhoon_model('cpu')
            
            assert model is None

    def test_load_typhoon_model_auto_cpu(self, mock_model):
        """Test auto device selection when CUDA not available"""
        with patch('typhoon_asr_inference.torch.cuda.is_available', return_value=False):
            with patch('typhoon_asr_inference.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model) as mock_load:
                typhoon_asr_inference.load_typhoon_model('auto')
                
                # Check that mock was called with correct device (as string)
                mock_load.assert_called_once()
                call_args = mock_load.call_args
                assert call_args.kwargs['model_name'] == "scb10x/typhoon-asr-realtime"
                assert str(call_args.kwargs['map_location']) == 'cpu'

    def test_load_typhoon_model_auto_cuda(self, mock_model):
        """Test auto device selection when CUDA available"""
        with patch('typhoon_asr_inference.torch.cuda.is_available', return_value=True):
            with patch('typhoon_asr_inference.nemo_asr.models.ASRModel.from_pretrained', return_value=mock_model) as mock_load:
                typhoon_asr_inference.load_typhoon_model('auto')
                
                # Check that mock was called with correct device (as string)
                mock_load.assert_called_once()
                call_args = mock_load.call_args
                assert call_args.kwargs['model_name'] == "scb10x/typhoon-asr-realtime"
                assert str(call_args.kwargs['map_location']) == 'cuda'

    def test_basic_transcription(self, mock_model):
        """Test basic transcription function"""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            sample_rate = 16000
            audio_data = np.zeros(16000)  # 1 second of silence
            import soundfile as sf
            sf.write(f.name, audio_data, sample_rate)
            temp_file = f.name
        
        try:
            transcription, processing_time = typhoon_asr_inference.basic_transcription(mock_model, temp_file)
            
            assert transcription == "สวัสดี นี่คือการทดสอบ"
            assert isinstance(processing_time, float)
            assert processing_time >= 0
        finally:
            os.remove(temp_file)

    def test_transcription_with_timestamps(self, mock_model_with_hypotheses):
        """Test transcription with timestamps function"""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            sample_rate = 16000
            audio_data = np.zeros(16000)  # 1 second of silence
            import soundfile as sf
            sf.write(f.name, audio_data, sample_rate)
            temp_file = f.name
        
        try:
            transcription, timestamps, processing_time = typhoon_asr_inference.transcription_with_timestamps(
                mock_model_with_hypotheses, temp_file
            )
            
            assert transcription == "สวัสดี นี่คือการทดสอบ"
            assert isinstance(timestamps, list)
            assert len(timestamps) > 0
            assert isinstance(processing_time, float)
            
            # Check timestamp structure
            ts = timestamps[0]
            assert 'word' in ts
            assert 'start' in ts
            assert 'end' in ts
        finally:
            os.remove(temp_file)

    def test_transcription_with_timestamps_empty_result(self):
        """Test transcription with timestamps when result is empty"""
        mock_model = Mock()
        mock_model.transcribe.return_value = []
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            sample_rate = 16000
            audio_data = np.zeros(16000)
            import soundfile as sf
            sf.write(f.name, audio_data, sample_rate)
            temp_file = f.name
        
        try:
            transcription, timestamps, processing_time = typhoon_asr_inference.transcription_with_timestamps(
                mock_model, temp_file
            )
            
            assert transcription == ""
            assert timestamps == []
            assert isinstance(processing_time, float)
        finally:
            os.remove(temp_file)

    def test_main_function_basic(self, sample_audio_file, mock_model, capsys):
        """Test main function with basic transcription"""
        with patch('typhoon_asr_inference.load_typhoon_model', return_value=mock_model):
            with patch('typhoon_asr_inference.prepare_audio', return_value=(True, "processed_test.wav", {"duration": 1.0})):
                with patch('sys.argv', ['typhoon_asr_inference.py', sample_audio_file]):
                    result = typhoon_asr_inference.main()
                    
                    assert result == 0
                    captured = capsys.readouterr()
                    assert "TRANSCRIPTION RESULTS" in captured.out
                    assert "สวัสดี นี่คือการทดสอบ" in captured.out

    def test_main_function_file_not_found(self, capsys):
        """Test main function with non-existent file"""
        with patch('sys.argv', ['typhoon_asr_inference.py', 'nonexistent.wav']):
            result = typhoon_asr_inference.main()
            
            assert result == 1
            captured = capsys.readouterr()
            assert "Input file not found" in captured.out

    def test_main_function_model_loading_failure(self, sample_audio_file, capsys):
        """Test main function when model loading fails"""
        with patch('typhoon_asr_inference.load_typhoon_model', return_value=None):
            with patch('sys.argv', ['typhoon_asr_inference.py', sample_audio_file]):
                result = typhoon_asr_inference.main()
                
                assert result == 1

    def test_main_function_audio_processing_failure(self, sample_audio_file, mock_model, capsys):
        """Test main function when audio processing fails"""
        with patch('typhoon_asr_inference.load_typhoon_model', return_value=mock_model):
            with patch('typhoon_asr_inference.prepare_audio', return_value=(False, None, {"error": "Test error"})):
                with patch('sys.argv', ['typhoon_asr_inference.py', sample_audio_file]):
                    result = typhoon_asr_inference.main()
                    
                    assert result == 1
                    captured = capsys.readouterr()
                    assert "Audio processing failed" in captured.out

    def test_argument_parsing(self):
        """Test command line argument parsing"""
        parser = argparse.ArgumentParser(description="Typhoon ASR Real-Time Inference")
        parser.add_argument("input_file", help="Input audio file path")
        parser.add_argument("--with-timestamps", action="store_true",
                           help="Generate estimated word timestamps")
        parser.add_argument("--device", choices=['auto', 'cpu', 'cuda'], default='auto',
                           help="Processing device (default: auto)")
        
        # Test basic arguments
        args = parser.parse_args(['test.wav'])
        assert args.input_file == 'test.wav'
        assert args.with_timestamps is False
        assert args.device == 'auto'
        
        # Test with timestamps
        args = parser.parse_args(['test.wav', '--with-timestamps'])
        assert args.with_timestamps is True
        
        # Test with device
        args = parser.parse_args(['test.wav', '--device', 'cuda'])
        assert args.device == 'cuda'

    def test_cleanup_temporary_file(self, sample_audio_file, mock_model):
        """Test that temporary files are cleaned up"""
        processed_file = "processed_test.wav"
        
        # Create a fake processed file
        with open(processed_file, 'w') as f:
            f.write("dummy")
        
        with patch('typhoon_asr_inference.load_typhoon_model', return_value=mock_model):
            with patch('typhoon_asr_inference.prepare_audio', return_value=(True, processed_file, {"duration": 1.0})):
                with patch('sys.argv', ['typhoon_asr_inference.py', sample_audio_file]):
                    typhoon_asr_inference.main()
                    
                    # File should be cleaned up
                    assert not os.path.exists(processed_file)

    def test_rtf_calculation_real_time(self, sample_audio_file, mock_model, capsys):
        """Test RTF calculation for real-time capable processing"""
        # Mock fast processing (less than audio duration)
        mock_model.transcribe.side_effect = lambda audio: ["test"]
        
        with patch('typhoon_asr_inference.load_typhoon_model', return_value=mock_model):
            with patch('typhoon_asr_inference.prepare_audio', return_value=(True, "processed_test.wav", {"duration": 2.0})):
                with patch('time.time', side_effect=[0, 0.5]):  # 0.5 seconds processing time
                    with patch('sys.argv', ['typhoon_asr_inference.py', sample_audio_file]):
                        result = typhoon_asr_inference.main()
                        
                        assert result == 0
                        captured = capsys.readouterr()
                        assert "Real-time capable!" in captured.out

    def test_rtf_calculation_batch(self, sample_audio_file, mock_model, capsys):
        """Test RTF calculation for batch processing"""
        # Mock slow processing (more than audio duration)
        mock_model.transcribe.side_effect = lambda audio: ["test"]
        
        with patch('typhoon_asr_inference.load_typhoon_model', return_value=mock_model):
            with patch('typhoon_asr_inference.prepare_audio', return_value=(True, "processed_test.wav", {"duration": 1.0})):
                with patch('time.time', side_effect=[0, 2.0]):  # 2 seconds processing time
                    with patch('sys.argv', ['typhoon_asr_inference.py', sample_audio_file]):
                        result = typhoon_asr_inference.main()
                        
                        assert result == 0
                        captured = capsys.readouterr()
                        assert "Batch processing" in captured.out
