FROM python:3.12-slim
RUN useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY compare_app.py csvdiff.py ./
COPY tablecmp/ tablecmp/
ENV STREAMLIT_SERVER_HEADLESS=true STREAMLIT_SERVER_ADDRESS=0.0.0.0 STREAMLIT_SERVER_PORT=8501     STREAMLIT_BROWSER_GATHER_USAGE_STATS=false STREAMLIT_LOGGER_LEVEL=warning     COMPARE_DATA_DIR=/data COMPARE_OUT_DIR=/out COMPARE_WORK_DIR=/work
RUN mkdir -p /data /out /work /home/app/.crosshire-compare && chown -R app:app /data /out /work /home/app
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s   CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
CMD ["python", "compare_app.py"]
