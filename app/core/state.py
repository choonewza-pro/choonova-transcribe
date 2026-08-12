"""
Global state for tracking active worker subprocesses.
Extracted to avoid circular dependencies between main.py and the modular routers.
"""
from typing import Dict
import subprocess

# Track isolated worker subprocesses so the watchdog can detect crashes
_active_workers: Dict[str, "subprocess.Popen"] = {}

# Track running video compressor subprocesses (FFmpeg jobs). 
_active_compress_workers: Dict[str, "subprocess.Popen"] = {}
