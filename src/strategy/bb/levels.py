"""BB 전략의 진입/손절 레벨 상수.

BBStrategy.__init__이 config 값으로 이 모듈 전역을 재바인딩할 수 있으므로
(하위 호환을 위한 기존 `global LONG_ENTRY_LEVELS` 패턴 유지)
레벨을 참조하는 코드는 반드시 `from . import levels` 후 `levels.LONG_ENTRY_LEVELS`
형태로 지연 접근해야 한다. `from .levels import LONG_ENTRY_LEVELS`로 import하면
mutation이 반영되지 않는다.
"""

LONG_ENTRY_LEVELS = [
    {"bbp": 0.15, "ratio": 0.30, "step": 1},  # 1차 진입
    {"bbp": 0.10, "ratio": 0.30, "step": 2},  # 2차 물타기
    {"bbp": 0.05, "ratio": 0.30, "step": 3},  # 3차 물타기
]

SHORT_ENTRY_LEVELS = [
    {"bbp": 0.85, "ratio": 0.30, "step": 1},  # 1차 진입
    {"bbp": 0.90, "ratio": 0.30, "step": 2},  # 2차 물타기
    {"bbp": 0.95, "ratio": 0.30, "step": 3},  # 3차 물타기
]

LONG_STOP_LEVELS = [
    {"bbp": -0.05, "stop_ratio": 1.00},  # BB 하단 이탈 → 전량 손절
]

SHORT_STOP_LEVELS = [
    {"bbp": 1.05, "stop_ratio": 1.00},  # BB 상단 이탈 → 전량 손절
]
