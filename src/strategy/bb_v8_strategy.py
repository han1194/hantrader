"""하위 호환 shim. 실제 구현은 src/strategy/bb/v8.py 로 이동했다."""

from .bb.v8 import BBV8Strategy  # noqa: F401

__all__ = ["BBV8Strategy"]
