FROM python:3.13-slim

WORKDIR /app

COPY requirements/ ./requirements/
RUN pip install --no-cache-dir -r requirements/base.txt

COPY src/ src/

EXPOSE 8000

#CMD ["uvicorn", "brewctl.api.server:app", "--host", "0.0.0.0", "--reload"]
ENV PYTHONPATH=/app/src
CMD ["fastapi", "dev",  "src/brewctl/main.py", "--host", "0.0.0.0"]