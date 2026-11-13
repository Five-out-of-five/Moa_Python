FROM python:3.12-slim

WORKDIR /app

# 의존성은 lock 파일 버전 그대로 설치한다. 빌드할 때마다 최신 버전이 깔려 동작이 바뀌는 것을 막는다.
# 코드보다 먼저 복사해 레이어 캐시를 살린다(코드만 바뀌면 이 단계는 다시 돌지 않는다).
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY app ./app

# root 로 돌리지 않는다.
RUN useradd --create-home --uid 10001 moa
USER moa

EXPOSE 8000

# LLM 호출은 I/O 대기라 워커 수보다 async 동시성이 먼저다. 키 쿨다운 상태를 프로세스가 들고 있으므로
# 워커를 늘리면 워커마다 따로 센다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
