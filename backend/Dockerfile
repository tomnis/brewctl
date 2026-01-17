FROM python:3.13-slim

WORKDIR /app

COPY requirements/ ./requirements/
RUN pip install --no-cache-dir -r requirements/base.txt

COPY src/ ./

EXPOSE 8000

#CMD ["uvicorn", "brewserver:server:app", "--host", "0.0.0.0", "--reload"]
CMD ["fastapi", "dev",  "src/brewserver/server.py", "--host", "0.0.0.0"]