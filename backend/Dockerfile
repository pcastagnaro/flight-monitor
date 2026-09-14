FROM python:3.12-slim
WORKDIR /app
COPY requirements*.txt ./
ARG INSTALL_EXPERIMENTAL=false
ARG INSTALL_BROWSER=false
RUN pip install --no-cache-dir -r requirements.txt
RUN if [ "$INSTALL_BROWSER" = "true" ]; then pip install --no-cache-dir -r requirements-browser.txt && playwright install --with-deps chromium; elif [ "$INSTALL_EXPERIMENTAL" = "true" ]; then pip install --no-cache-dir -r requirements-experimental.txt; fi
COPY . .
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
