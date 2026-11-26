FROM python:3.8-slim AS base
WORKDIR /app
COPY fetch_code.py .
RUN python fetch_code.py /opt/rcaeval
RUN pip install --no-cache-dir -r /opt/rcaeval/requirements_torai.lock
RUN cp /opt/rcaeval/lib/causallearn/utils/PCUtils/SkeletonDiscovery.py /usr/local/lib/python3.8/site-packages/causallearn/utils/PCUtils/ \
 && cp /opt/rcaeval/lib/causallearn/graph/GraphClass.py /usr/local/lib/python3.8/site-packages/causallearn/graph/
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/opt/rcaeval:/app
ENV MPLBACKEND=Agg
COPY anomalyguard anomalyguard

FROM base AS test
COPY requirements-dev.txt pytest.ini ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests tests
CMD ["pytest"]

FROM base AS runtime
RUN useradd --system --no-create-home anomalyguard
USER anomalyguard
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)"
CMD ["python", "-m", "anomalyguard"]
