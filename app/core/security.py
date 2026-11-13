"""내부 호출 검증. 이 서버는 Spring 만 부른다."""

import secrets

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.core.errors import AiErrorCode, AiException


async def verify_internal_caller(
    x_internal_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.internal_api_key
    if not expected:
        # 키를 설정하지 않은 로컬 환경. prod 는 설정 검증에서 이미 막혔다.
        return
    # 길이·내용 비교 시간을 같게 해서 키를 한 글자씩 맞춰 보는 공격을 막는다.
    if not x_internal_api_key or not secrets.compare_digest(x_internal_api_key, expected):
        raise AiException(AiErrorCode.UNAUTHORIZED)
