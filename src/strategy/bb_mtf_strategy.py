"""하위 호환 shim. 실제 구현은 src/strategy/bb/mtf.py 로 이동했다."""

from .bb.mtf import BBMTFStrategy, ADJACENT_TF  # noqa: F401

__all__ = ["BBMTFStrategy", "ADJACENT_TF"]
