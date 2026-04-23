"""하위 호환 shim. 실제 구현은 src/strategy/bb/v5.py 로 이동했다."""

from .bb.v5 import BBV5Strategy  # noqa: F401

__all__ = ["BBV5Strategy"]
