# Alternative til export all is to set up an extra target with the export on the dep side
# pytest: export PYTHONPATH = $(pwd)
.EXPORT_ALL_VARIABLES:
PYTHONPATH = $(shell pwd)

all:
	@echo Check makefile for targets

boink:
	@echo $(PYTHONPATH)

pytest:
	pytest --asyncio-mode=auto tests -v

# python3 -m stevneweb.test_mod
# pytest-3 -v --ignore DL --ignore tornado --ignore tornado-6.0.3 --ignore tools/zscript_test.py

