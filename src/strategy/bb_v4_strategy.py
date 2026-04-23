"""하위 호환 shim. 실제 구현은 src/strategy/bb/v4.py 로 이동했다."""

from .bb.v4 import BBV4Strategy  # noqa: F401

__all__ = ["BBV4Strategy"]
