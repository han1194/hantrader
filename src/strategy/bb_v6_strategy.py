"""하위 호환 shim. 실제 구현은 src/strategy/bb/v6.py 로 이동했다."""

from .bb.v6 import BBV6Strategy  # noqa: F401

__all__ = ["BBV6Strategy"]
