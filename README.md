# Flow-Based Toolkit

Theory, worked examples and runnable code for **flow-based capacity calculation**
in interconnected power systems — PTDF, RAM, CNEC, the flow-based domain, market
coupling, and remedial-action optimisation (RAO) — with everything computed and
**verified using [pypowsybl](https://pypowsybl.readthedocs.io) and
[OpenRAO](https://powsybl.readthedocs.io/projects/openrao/)**.

The written theory is in French (see `docs/`); the code and this README are in English.

---

## What's inside

- **A theory document** (`docs/flowbased.tex`, in French — build the PDF with
  `make pdfs`) covering, from first
  principles: the DC power-flow derivation of **PTDF** (`PTDF = Bd·A·X`), the
  nodal→zonal step via **GSK**, the **RAM** (`Fmax − Fref − FRM`, min-RAM 70 %),
  the **CNEC** constraints, the **flow-based domain** (a polytope) and its
  **vertices**, a geometric reading of the hyperplanes, and a beginner-friendly
  operational tour — actors (TSOs, RCCs, JAO, NEMOs), time horizons, the
  coordinated capacity-calculation process, the net-position forecast (D2CF),
  market coupling and its algorithms (SDAC/EUPHEMIA, SIDC), the coordinated
  security analysis (CSA) for the Core region, and the RAO / CASTOR algorithm —
  with diagrams and timelines throughout.
- **A fully-worked 3-zone example** reproduced three ways so the numbers match:
  by hand (matrix `B`), analytically in Python, and by pypowsybl.
- **Runnable scripts** (`src/`) where all the physics comes from pypowsybl:
  PTDF (nodal & zonal), reference flows, post-contingency PTDF, the flow-based
  domain (with each vertex validated by a load flow), and an OpenRAO
  remedial-action optimisation.

## Repository layout

```
flowbased-toolkit/
├── docs/
│   └── flowbased.tex               # the theory + operational document (French); build the PDF with `make pdfs`
├── src/
│   ├── ptdf_pypowsybl.py            # PTDF: NumPy analytic vs pypowsybl (asserted equal)
│   ├── theorie_flowbased_pypowsybl.py  # full chain + domain plot (→ figures/)
│   └── openrao_remedial_actions.py  # OpenRAO RAO: PST remedial action + DC cross-check
├── data/rao/                        # network + CRAC + parameters + GLSK (see NOTICE)
├── figures/                         # generated plots (a sample is committed)
├── scripts/fetch_rao_data.sh        # (re)download the RAO example resources
├── requirements.txt
├── Makefile
└── .github/workflows/ci.yml
```

## Requirements

- Python 3.10–3.12
- `pypowsybl==1.15.0` (pinned — the OpenRAO resources in `data/rao/` match this
  version; newer pypowsybl may expect newer CRAC/RaoParameters formats)
- numpy, pandas, matplotlib

pypowsybl ships self-contained native binaries, so **no separate Java install** is
needed.

```bash
python -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
```

## Usage

```bash
# 1) PTDF — analytic (B matrix) vs pypowsybl, with an equality assertion
python src/ptdf_pypowsybl.py

# 2) Full theory chain with pypowsybl: PTDF nodal/zonal (GSK), RAM, CNEC,
#    domain vertices, each vertex validated by a load flow, and a domain plot
python src/theorie_flowbased_pypowsybl.py     # writes figures/domaine_flowbased.png

# 3) OpenRAO: optimise a PST remedial action to maximise the minimum margin,
#    then cross-check the result with an independent DC load flow
python src/openrao_remedial_actions.py
```

Or via `make`:

```bash
make install    # pip install -r requirements.txt
make ptdf       # run example 1
make theory     # run example 2 (generates the figure)
make rao        # run example 3
make pdfs       # build the LaTeX document (needs a TeX Live install)
```

### Expected results (sanity check)

- PTDF for the equal-reactance triangle: `1/3` and `2/3`, with `PTDF_C = 0`
  (C is the slack). Analytic and pypowsybl values match to `< 1e-6`.
- The flow-based domain is an octagon with 8 vertices; at each vertex the flow
  on the active CNECs equals `±RAM` (checked by load flow).
- The OpenRAO example selects the Belgian PST, moves it to **tap −16**, and
  raises the minimum margin from **2666.7 → 2719.0 MW** (reproduced by DC load flow).

## Building the PDF

```bash
cd docs
pdflatex flowbased.tex && pdflatex flowbased.tex && pdflatex flowbased.tex   # 3× for the ToC and cross-refs
```

Note: the `.tex` source has `babel[french]` and `lmodern` commented out (they
were unavailable in the build environment used to generate the committed PDF).
With a full TeX Live install you can re-enable them for proper French
hyphenation and typography.

## Data provenance & licensing

- **Code and documents**: MIT (see `LICENSE`).
- **`data/rao/*`**: example resources taken from the
  [powsybl/pypowsybl](https://github.com/powsybl/pypowsybl) repository
  (tag `v1.15.0`, `data/rao/`), under **MPL-2.0** — see `NOTICE.md`. You can
  re-fetch them with `bash scripts/fetch_rao_data.sh`.

## References

- pypowsybl — https://pypowsybl.readthedocs.io
- OpenRAO (CASTOR) — https://powsybl.readthedocs.io/projects/openrao/
- ENTSO-E CACM / SDAC / SIDC — https://www.entsoe.eu/network_codes/cacm/
- JAO (flow-based domain, long-term auctions) — https://www.jao.eu
