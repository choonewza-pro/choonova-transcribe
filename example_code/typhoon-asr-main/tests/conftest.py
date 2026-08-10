import pytest
import os
import tempfile
import numpy as np
import soundfile as sf
from pathlib import Path


@pytest.fixture(scope="session")
def test_audio_dir():
    """Create a temporary directory for test audio files"""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def sample_audio_files(test_audio_dir):
    """Create multiple sample audio files for testing"""
    files = {}
    sample_rate = 16000
    duration = 1.0
    frequency = 440
    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio_data = np.sin(frequency * t * 2 * np.pi) * 0.3
    
    # Create files in different formats
    formats = ['.wav', '.mp3', '.m4a', '.flac']
    
    for fmt in formats:
        file_path = os.path.join(test_audio_dir, f"test_audio{fmt}")
        sf.write(file_path, audio_data, sample_rate)
        files[fmt] = file_path
    
    yield files
    
    # Cleanup is handled by TemporaryDirectory


@pytest.fixture
def thai_text_samples():
    """Sample Thai text for testing"""
    return {
        "short": "สวัสดี",
        "medium": "สวัสดี นี่คือการทดสอบ",
        "long": "สวัสดี นี่คือการทดสอบระบบการแปลงเสียงเป็นข้อความภาษาไทย",
        "empty": "",
        "with_spaces": "  สวัสดี  นี่คือ  การทดสอบ  ",
        "with_numbers": "สวัสดี 123 ทดสอบ",
        "mixed": "Hello สวัสดี test ทดสอบ"
    }
