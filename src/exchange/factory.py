import os

from src.config import ExchangeConfig
from src.utils.logger import setup_logger
from .base import ExchangeWrapper
from .upbit import UpbitWrapper

logger = setup_logger("hantrader.exchange")


def create_exchange(
    exchange_id: str,
    options: dict | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    testnet: bool = False,
) -> ExchangeWrapper:
    """거래소 래퍼 인스턴스를 생성한다.

    exchange_id에 따라 전용 래퍼 클래스를 반환한다:
    - "upbit": UpbitWrapper (현물 KRW, 레버리지/포지션 없음, testnet 미지원)
    - 그 외:   ExchangeWrapper (기본, 바이낸스 선물 등)
    """
    if exchange_id == "upbit":
        return UpbitWrapper(options=options, api_key=api_key, api_secret=api_secret)

    return ExchangeWrapper(
        exchange_id,
        options=options,
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
    )


def create_authenticated_exchange(exc_config: ExchangeConfig) -> ExchangeWrapper:
    """ExchangeConfig의 auth 환경변수에서 API 키를 로드하여 인증된 거래소를 생성한다.

    Args:
        exc_config: 거래소 설정 (api_key_env, api_secret_env, testnet_env 포함)

    Returns:
        인증된 ExchangeWrapper

    Raises:
        ValueError: API 키 환경변수가 설정되지 않았을 때
    """
    api_key = os.environ.get(exc_config.api_key_env, "") if exc_config.api_key_env else ""
    api_secret = os.environ.get(exc_config.api_secret_env, "") if exc_config.api_secret_env else ""
    testnet = (
        os.environ.get(exc_config.testnet_env, "false").lower() == "true"
        if exc_config.testnet_env
        else False
    )

    if not api_key or not api_secret:
        env_names = []
        if exc_config.api_key_env:
            env_names.append(exc_config.api_key_env)
        if exc_config.api_secret_env:
            env_names.append(exc_config.api_secret_env)
        raise ValueError(
            f"API 키가 설정되지 않았습니다.\n"
            f"  .env 파일에 다음 환경변수를 설정하세요:\n"
            f"  " + "\n  ".join(f"{name}=your_value" for name in env_names)
        )

    logger.info(f"인증 거래소 생성: {exc_config.type} (testnet={testnet})")

    return create_exchange(
        exc_config.type,
        options=exc_config.options or None,
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
    )
