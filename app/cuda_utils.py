"""
Shared CUDA error detection helpers used by both the long-form job worker and
the realtime WebSocket path.

Transient CUDA driver errors (e.g. "CUDA driver error: device not ready") can hit
long-running services after many consecutive transcribe calls. More seriously,
PyTorch CUDACachingAllocator internal-state corruption (a stale handle in the
allocator's tracking map) cannot be fixed with empty_cache(); it requires a full
CUDA context rebuild via cudaDeviceReset() + model reload.
"""
from typing import Tuple

# Transient CUDA driver errors that are safe to retry after backoff + cache clear.
_CUDA_ERROR_KEYWORDS: Tuple[str, ...] = (
    "cuda",
    "device not ready",
    "driver error",
    "nvidia",
    "cublas",
    "cudnn",
    "out of memory",
    "illegal memory access",
    "device-side assert",
)
# Allocator/context corruption that is NOT recoverable by retrying alone; it needs
# a full CUDA device reset (cudaDeviceReset) because the CUDA context is poisoned.
_ALLOCATOR_CORRUPTION_KEYWORDS: Tuple[str, ...] = (
    "internal assert",
    "cudacachingallocator",
    "handles_",
    "allocator",
    "illegal memory access",
    "device-side assert",
)


def is_cuda_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in _CUDA_ERROR_KEYWORDS)


def is_allocator_corruption(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in _ALLOCATOR_CORRUPTION_KEYWORDS)
