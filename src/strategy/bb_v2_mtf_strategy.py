"""하위 호환 shim. 실제 구현은 src/strategy/bb/v2_mtf.py 로 이동했다."""

from .bb.v2_mtf import BBV2MTFStrategy  # noqa: F401

__all__ = ["BBV2MTFStrategy"]
