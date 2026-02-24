FROM python:3.13-slim

WORKDIR /app

COPY requirements/ ./requirements/
RUN pip install --no-cache-dir -r requirements/base.txt

COPY src/ ./

EXPOSE 8000

#CMD ["uvicorn", "brewctl:server:app", "--host", "0.0.0.0", "--reload"]
CMD ["fastapi", "dev",  "src/brewctl/server.py", "--host", "0.0.0.0"]