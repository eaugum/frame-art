FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY frameart ./frameart
# The add-on's options are /data/options.json; the token and state.json stay in /data too
CMD ["python", "-u", "-m", "frameart", "--config", "/data/options.json"]
