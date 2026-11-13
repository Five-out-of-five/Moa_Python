FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 설치해 레이어 캐시를 살린다. 패키지 소스가 있어야 설치되므로 빈 패키지를 먼저 둔다.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install --no-cache-dir . && rm -rf app

COPY app ./app

# root 로 돌리지 않는다.
RUN useradd --create-home --uid 10001 moa
USER moa

EXPOSE 8000

# LLM 호출은 I/O 대기라 워커 수보다 async 동시성이 먼저다. 키 쿨다운 상태를 프로세스가 들고 있으므로
# 워커를 늘리면 워커마다 따로 센다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
