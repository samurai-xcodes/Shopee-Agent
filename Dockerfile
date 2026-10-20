FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG PIP_FIND_LINKS
ARG PIP_NO_INDEX
ARG PIP_TRUSTED_HOST
ARG DEBIAN_MIRROR=http://deb.debian.org
COPY requirements.txt requirements-runtime.lock ./
RUN pip install --no-cache-dir -r requirements-runtime.lock \
    && sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home agent \
    && mkdir -p /app/data/assets && chown -R agent:agent /app/data
COPY --chown=agent:agent . .
USER agent
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/ready', timeout=2)" || exit 1
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
