FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Run the app
CMD ["python", "src/dashboard/app.py"]# Rebuild Sun Apr 12 16:09:41 MST 2026
