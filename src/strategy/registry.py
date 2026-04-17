"""전략 레지스트리.

전략을 이름으로 등록/조회할 수 있는 플러그인 시스템.
새 전략 추가 시 @register_strategy("이름") 데코레이터만 붙이면
CLI에서 --strategy 이름 으로 사용 가능하다.
"""

from .base import BaseStrategy

_STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(name: str):
    """전략 클래스를 레지스트리에 등록하는 데코레이터."""
    def decorator(cls):
        _STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator


def create_strategy(name: str, **kwargs) -> BaseStrategy:
    """이름으로 전략 인스턴스를 생성한다.

    Args:
        name: 등록된 전략 이름 (예: "bb")
        **kwargs: 전략 생성자에 전달할 키워드 인자

    Raises:
        ValueError: 등록되지 않은 전략 이름
    """
    cls = _STRATEGY_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(sorted(_STRATEGY_REGISTRY.keys()))
        raise ValueError(f"Unknown strategy: '{name}'. Available: {available}")
    return cls(**kwargs)


def list_strategies() -> list[str]:
    """등록된 전략 이름 목록을 반환한다."""
    return sorted(_STRATEGY_REGISTRY.keys())
