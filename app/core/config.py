"""환경 설정.

값이 틀리면 기동 시점에 실패한다. 첫 요청에서야 터지는 것보다 못 뜨는 게 낫다.
"""

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---------- 실행 ----------
    app_env: str = Field(default="local", description="local / dev / prod")
    log_level: str = "INFO"

    # ---------- 내부 통신 ----------
    # Spring 이 X-Internal-Api-Key 헤더로 보낸다. 비어 있으면 검사하지 않는다(로컬 편의).
    # prod 에서는 비어 있으면 기동을 거부한다.
    internal_api_key: str = ""

    # ---------- Gemini ----------
    # 쉼표로 여러 개를 넣을 수 있다. 한 키가 429/401/403 을 내면 쿨다운에 넣고 다음 키로 넘어간다.
    gemini_api_key: str = ""
    # 한도에 걸린 키를 다시 쓰기까지 기다리는 시간(초). 분당 한도는 60초면 풀린다.
    gemini_key_cooldown_seconds: int = 300

    # 모델은 별칭(-latest)이 아니라 이름을 고정한다. 별칭은 예고 없이 바뀌어 프롬프트가 무효가 된다.
    # 짧고 자주 부르는 것(톤, 충돌 판정)은 Flash-Lite, 나머지는 Flash.
    gemini_model_tone: str = "gemini-3.5-flash-lite"
    gemini_model_conflict: str = "gemini-3.5-flash-lite"
    gemini_model_summary: str = "gemini-3.5-flash"
    gemini_model_compromise: str = "gemini-3.5-flash"
    gemini_model_layout: str = "gemini-3.5-flash"
    gemini_model_assistant: str = "gemini-3.5-flash"
    gemini_model_embedding: str = "gemini-embedding-001"

    # Spring 의 읽기 타임아웃이 30초라서, 재시도까지 합친 전체 시간을 그보다 짧게 둔다.
    gemini_deadline_seconds: float = 25.0
    # 같은 키로 다시 시도하는 횟수(일시 오류일 때). 키 전환은 키 개수만큼 따로 한다.
    gemini_max_retries: int = 2

    # content_embedding.embedding vector(768) 과 같아야 한다.
    embedding_dimension: int = 768

    # ---------- AI 스텁 (로컬 개발·부하 테스트) ----------
    # 켜면 Gemini 를 부르지 않고 "[더미]" 응답을 준다. 키 없이 Spring 연동을 확인할 때 쓴다.
    # prod 에서는 켤 수 없다.
    ai_stub_mode: bool = False
    ai_stub_delay_ms: int = 0
    ai_stub_jitter_ms: int = 0
    ai_stub_fail_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.app_env == "prod":
            if self.ai_stub_mode:
                raise ValueError("AI_STUB_MODE 는 prod 에서 쓸 수 없습니다.")
            if not self.internal_api_key:
                raise ValueError("prod 에서는 INTERNAL_API_KEY 가 필요합니다.")
        if not self.ai_stub_mode and not self.gemini_api_keys:
            raise ValueError("GEMINI_API_KEY 에 유효한 키가 없습니다. (쉼표로 여러 개 지정 가능)")
        return self

    @property
    def gemini_api_keys(self) -> list[str]:
        """쉼표로 구분된 키 목록. 순서를 유지하고 중복은 지운다(같은 키는 한도도 같이 소진된다)."""
        unique: dict[str, None] = {}
        for raw in self.gemini_api_key.split(","):
            key = raw.strip()
            if key:
                unique.setdefault(key, None)
        return list(unique)


@lru_cache
def get_settings() -> Settings:
    """프로세스당 한 번만 읽는다. 테스트에서는 cache_clear() 후 다시 읽는다."""
    return Settings()
