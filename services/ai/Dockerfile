# --- build stage: wheels ------------------------------------------------------
FROM python:3.12-slim AS build
WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# --- runtime stage --------------------------------------------------------------
FROM python:3.12-slim
RUN useradd -m -u 10001 wakili
WORKDIR /app
COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels
COPY app ./app
COPY gen ./gen
ENV PYTHONPATH=/app:/app/gen PYTHONUNBUFFERED=1
USER wakili
EXPOSE 50051 8081
CMD ["python", "-m", "app.server"]
