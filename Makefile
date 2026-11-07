.PHONY: test demo package all

test:
	python3 -m pytest -q

demo:
	bash tools/demo.sh

package:
	python3 tools/package_skills.py

all: test demo package
