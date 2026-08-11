"""
Settings domain entities.
"""

from dataclasses import dataclass

@dataclass
class ModelSettings:
    """Represents runtime VRAM / ASR model residency settings."""
    model_load_mode: str  # 'always' | 'idle'
    model_idle_timeout_sec: float
