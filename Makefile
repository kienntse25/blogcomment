.PHONY := venv redis worker pipeline all

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip wheel
	$(PIP) install -r requirements.txt

redis:
	sudo systemctl start redis-server

worker:
	. $(VENV)/bin/activate && celery -A src.tasks worker --loglevel=info

pipeline:
	. $(VENV)/bin/activate && $(PY) push_jobs_from_excel.py --input data/comments.xlsx --output data/comments_out.xlsx

all: redis worker
