"""하위 호환 shim. 실제 구현은 src/strategy/bb/v3.py 로 이동했다."""

from .bb.v3 import BBV3Strategy  # noqa: F401

__all__ = ["BBV3Strategy"]
