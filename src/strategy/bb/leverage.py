"""BB 전략 동적 레버리지 계산."""


def calc_bb_leverage(
    bb_width: float,
    leverage_max: int,
    leverage_min: int,
) -> int:
    """BB width 크기에 따라 레버리지를 동적으로 조정한다.

    BB width가 클수록 변동성이 높으므로 레버리지를 낮춘다.
    leverage_max ~ leverage_min 사이를 4단계로 균등 분배한다.
    """
    # max ~ min 사이를 4단계로 균등 분배
    step = (leverage_max - leverage_min) / 3
    leverages = [
        leverage_max,
        int(leverage_max - step),
        int(leverage_max - step * 2),
        leverage_min,
    ]

    # BB width를 4단계로 구분 (일반적으로 BB width는 0.01 ~ 0.10+ 범위)
    thresholds = [0.02, 0.04, 0.06, 0.08]

    for i, threshold in enumerate(thresholds):
        if bb_width < threshold:
            return leverages[i]

    return leverage_min
