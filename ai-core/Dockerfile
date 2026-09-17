FROM python:3.12-slim

WORKDIR /app

# 의존성을 먼저 복사해서 코드만 바뀔 때 레이어 캐시를 재사용한다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY mock ./mock
COPY data ./data
COPY scripts ./scripts

EXPOSE 8000

# --workers 1 고정. job 상태를 in-memory dict로 들고 있어서 워커가 2개 이상이면
# POST /jobs를 처리한 프로세스와 GET /jobs/{id}를 처리하는 프로세스가 달라지고,
# 방금 만든 job이 404로 나온다. (ai-core 플랜 05절 함정 1)
#
# 포트를 $PORT로 받는다. Render 같은 PaaS는 자기가 정한 포트를 환경 변수로 넘기고,
# 거기 바인딩하지 않으면 외부에서 안 붙는다. 로컬에서는 8000으로 떨어진다.
# sh -c + exec을 쓰는 이유는 변수를 확장하면서도 uvicorn이 PID 1이 되게 하려는 것
# (PID 1이 아니면 컨테이너 종료 시 SIGTERM을 못 받는다).
CMD ["sh", "-c", "exec uvicorn mock.mock_server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
