.PHONY := venv redis worker pipeline campaign all

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
INPUT ?= data/comments.xlsx
OUTPUT ?= data/comments_out.xlsx

venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip wheel
	$(PIP) install -r requirements.txt

redis:
	sudo systemctl start redis-server

worker:
	. $(VENV)/bin/activate && celery -A src.tasks worker --loglevel=info

pipeline:
	. $(VENV)/bin/activate && INPUT_XLSX=$(INPUT) OUTPUT_XLSX=$(OUTPUT) $(PY) push_jobs_from_excel.py

campaign:
	./scripts/run_campaign.sh --input $(INPUT) --output $(OUTPUT)

all: redis worker
