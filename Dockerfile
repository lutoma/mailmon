FROM python:3.10.7-bullseye as requirements-stage

WORKDIR /tmp
RUN pip install poetry
COPY ./pyproject.toml ./poetry.lock* /tmp/
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes

FROM python:3.10.7-alpine

WORKDIR /app
COPY --from=requirements-stage /tmp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY mailmon.py /app
RUN mkdir /data

WORKDIR /app
CMD ["python", "-u", "mailmon.py", "/data/config.yml"]
