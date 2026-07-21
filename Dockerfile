FROM python:3.12-slim

WORKDIR /app

# Copy only what's needed to serve the dashboard
COPY proxy.py .
COPY requirements.txt .
COPY pages/ pages/
COPY assets/ assets/
COPY data/ data/
COPY prompts/ prompts/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

CMD ["python3", "proxy.py"]
