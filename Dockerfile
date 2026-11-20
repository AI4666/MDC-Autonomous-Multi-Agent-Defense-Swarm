FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run automated pytest suite and all 4 evaluation scenarios + ablations by default
CMD ["python", "run_part5.py", "--scenario", "all"]
