"""하위 호환 shim. 실제 구현은 src/strategy/bb/v7.py 로 이동했다."""

from .bb.v7 import BBV7Strategy  # noqa: F401

__all__ = ["BBV7Strategy"]
