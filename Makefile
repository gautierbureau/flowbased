.PHONY: help install ptdf theory rao pdfs fetch-data clean

help:
	@echo "make install     - install Python dependencies"
	@echo "make ptdf        - run PTDF example (analytic vs pypowsybl)"
	@echo "make theory      - run full flow-based theory example (+ figure)"
	@echo "make rao         - run OpenRAO remedial-action example"
	@echo "make pdfs        - build the LaTeX document (needs TeX Live)"
	@echo "make fetch-data  - (re)download the OpenRAO example resources"
	@echo "make clean       - remove LaTeX build artifacts"

install:
	pip install -r requirements.txt

ptdf:
	python src/ptdf_pypowsybl.py

theory:
	python src/theorie_flowbased_pypowsybl.py

rao:
	python src/openrao_remedial_actions.py

pdfs:
	cd docs && pdflatex -interaction=nonstopmode flowbased.tex && pdflatex -interaction=nonstopmode flowbased.tex && pdflatex -interaction=nonstopmode flowbased.tex

fetch-data:
	bash scripts/fetch_rao_data.sh

clean:
	cd docs && rm -f *.aux *.log *.out *.toc *.fls *.fdb_latexmk *.synctex.gz
