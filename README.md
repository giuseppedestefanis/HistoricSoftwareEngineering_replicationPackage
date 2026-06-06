# Replication Package — Historic Software Engineering: Insights from Deluxe Paint for the Amiga

Replication package for:

> **Historic Software Engineering: Insights from Deluxe Paint for the Amiga**
> Giuseppe Destefanis (University College London), Yann-Gaël Guéhéneuc (Concordia University), and Fabio Calefato (University of Bari)

The paper performs software archaeology on the *Deluxe Paint V1* source code (Electronic Arts, 1985) for the Commodore Amiga (Motorola 68000 at 7.16 MHz, 256 KB RAM). This package lets reviewers independently reproduce the quantitative results.

The codebase comprises **88 source files** (77 `.C` + 11 `.H`), **546 functions**, **17,001 lines of code**, and a total cyclomatic complexity of **1,223**.

---

## Contents

```
.
├── DeluxePaint_Analysis.ipynb   # Reproduces RQ2, RQ4, RQ5 (analysis notebook)
├── verify_patterns.py           # Reproduces RQ3 (28 design-pattern antecedents)
├── requirements.txt             # Notebook dependencies (verify_patterns needs none)
└── data/
    └── metrics/                 # Understand SciTools metric exports + functional categories
        ├── file.csv                       # 88 files × file-level metrics
        ├── function.csv                   # 546 functions × function-level metrics
        ├── source_FileDependencies.csv    # file-to-file dependency edges
        ├── file_categories.csv            # functional category of each .C file (RQ5 category analysis)
        └── Deluxe_Paint_V1_Amiga_source03.csv  # comprehensive export (reference)
```

The repository ships the **derived metric exports** (measurements), not the Deluxe Paint source code itself (see [Obtaining the source code](#obtaining-the-source-code)).

---

## Which research question is answered where

The paper answers five research questions. This package reproduces the **quantitative** ones; RQ1 (development and quality) is qualitative and reported in the paper.

| Paper RQ | Topic | Reproduced by |
|---|---|---|
| RQ1 | How and by whom *DPaint* was developed; overall quality | *paper only (qualitative + recompilation)* |
| **RQ2** | Architectural styles (dependency structure) | **`DeluxePaint_Analysis.ipynb`** |
| **RQ3** | Design patterns | **`verify_patterns.py`** |
| **RQ4** | Coding idioms | **`DeluxePaint_Analysis.ipynb`** |
| **RQ5** | Complexity distribution | **`DeluxePaint_Analysis.ipynb`** |

> The notebook addresses the three quantitative questions — **RQ2**, **RQ5**, and **RQ4** — and each section is headed with the paper's own question number.

---

## Quick start

```bash
pip install -r requirements.txt          # for the notebook (verify_patterns needs nothing)

# Reproduce RQ2/RQ4/RQ5 — run the notebook top to bottom (Jupyter or Colab):
jupyter notebook DeluxePaint_Analysis.ipynb

# Reproduce RQ3 — verify the 28 design patterns against the source code:
python verify_patterns.py /path/to/deluxe_paint_source_code/      # -> 28/28 confirmed
```

The notebook loads `data/metrics/*.csv` automatically when run from the repository root. On Google Colab it falls back to uploading `file.csv`, `function.csv`, and `source_FileDependencies.csv`.

---

## The analysis notebook → paper values (RQ2, RQ4, RQ5)

Run the notebook top to bottom. Each section below prints the values reported in the paper.

### RQ2 — Architectural styles

| Notebook section | Reproduces (paper value) |
|---|---|
| **Build Dependency Network Graph** | Internal dependency graph: **70 nodes, 366 edges** (external Amiga-OS headers excluded). Hub files by in-degree: **SYSTEM.H 58, PRISM.H 48, PRISM.C 27**. Top betweenness: **PRISM.C 0.137**. |
| **RQ2: Dependency Network Analysis** | Hub-and-spoke architecture centred on `PRISM.C` / `PRISM.H`. |
| **RQ2 Visualization 3: Centrality Analysis** | Betweenness, in-degree, eigenvector and PageRank rankings (Table 4: top-10 by betweenness and in-degree). |
| **RQ2 Visualization 4: Community Detection** | **5 communities** via greedy modularity, **modularity Q = 0.191**, sizes **17, 16, 15, 13, 9**. |
| **RQ2 Visualization 6: Network Metrics Dashboard** | Density 0.076, average path length 2.03, diameter 4, most-depended-upon file SYSTEM.H (58). |
| **RQ2 Visualization 7: Network Robustness** | Removing the top-10 by **betweenness → 5 components / 78.6%** connectivity; by **in-degree → 18 components / 60.0%**. |

### RQ4 — Coding idioms

| Notebook section | Reproduces (paper value) |
|---|---|
| **RQ4: Memory-Conscious Design Analysis** | **Code density 0.24** (executable lines / total), **comment density 0.20**, **preprocessor density 0.09**; **mean function parameters 2.7** (median 2). |
| **RQ4: Coupling and Cohesion Analysis** | Martin's instability index. The most stable files (I = 0) are the headers **SYSTEM.H (Ca = 58), PRISM.H (Ca = 48), PNTS.H (Ca = 12)**; mean instability ≈ 0.48. |

### RQ5 — Complexity distribution

| Notebook section | Reproduces (paper value) |
|---|---|
| **RQ5: Complexity Distribution Analysis** | File-level CC: mean 13.9, median 3, **max 117 (PALETTE.C)**. Function-level CC: **mean 2.2**, median 1, **max 74 (mainCproc)**. **94% of functions have CC ≤ 5.** |
| **RQ5: Functional Category Analysis** | **Table 8** — the 77 `.C` files grouped into seven functional categories: UI/Interaction (16 files, 4,389 LOC, 472 CC), System/Init (15, 1,557, 110), Bitmap/Blitter (13, 3,089, 161), File I/O (10, 2,058, 45), Palette/Colour (8, 2,299, 208), Drawing/Graphics (8, 1,284, 96), Transforms (7, 1,206, 131). The category of each file is provided in `data/metrics/file_categories.csv`. |
| **RQ5: Correlation Analysis** | **LOC ~ CC Pearson r = 0.72** (over the 56 files with non-zero complexity); function nesting ~ CC r = 0.50. |
| **RQ5 Visualization 5: Comparative Performance Tables** | **Table 7** — top-10 files by sum cyclomatic complexity (PALETTE.C 117, …). |

> **Dependencies:** the notebook needs `pandas`, `numpy`, `networkx`, `scipy`, `matplotlib`, `seaborn`, `plotly==5.24.1`, `scikit-learn`, and `statsmodels` (see `requirements.txt`). `plotly` is pinned to 5.x because the figures use the 5.x colorbar API.

---

## Pattern verification → RQ3 (`verify_patterns.py`)

Independently verifies the **28 design-pattern antecedents** (paper Section 4.3 and Table 6) against the source code by explicit evidence checks — specific function definitions, struct definitions, macros, dispatch tables, and line ranges. It uses no AI and no external dependencies (standard library only).

```bash
python verify_patterns.py /path/to/deluxe_paint_source_code/             # verification mode
python verify_patterns.py /path/to/deluxe_paint_source_code/ --discover  # heuristic discovery mode
```

- **Verification mode (default):** for each of the 28 patterns, confirms the cited code structures exist. Expected result on the unmodified source: **28/28 patterns confirmed (174 evidence checks)**. Exit code 0.
- **Discovery mode (`--discover`):** scans all files for generic structural signatures (function-pointer arrays, struct-embedding chains, push/pop pairs, callback fields, …) with no prior knowledge of names, demonstrating the patterns are structurally present rather than cherry-picked.

| # | Family | Pattern | Primary evidence |
|---|---|---|---|
| 1–4 | Structural | Façade (Graphics / Blitter / Bitmap Mem. / Windowing) | PGRAPH.C; BLITOPS.C, MASKBLIT.C; BITMAPS.C; PANE.C |
| 5–6 | Structural | Adapter (Coordinates / IFF Format) | PRISM.H; DPIFF.C, ILBMR/W.C |
| 7–8 | Structural | Decorator (BMOB layers / IMode flags) | PRISM.H |
| 9–11 | Behavioural | Command (8-slot procs / Undo tags / Menu dispatch) | PAINTW.C; MAINMAG.C, PRISM.H; MENU.C |
| 12–13 | Behavioural | Strategy (Pixel writers / Geometric primitives) | PGRAPH.C; GEOM.C, CONIC.C |
| 14 | Behavioural | State (IMode FSM) | PAINTW.C |
| 15 | Behavioural | Observer (Pane callbacks + VBlank) | PANE.C, CCYCLE.C |
| 16 | Behavioural | Template Method | PAINTW.C, MODES.C, PSYM.C |
| 17–18 | Creational | Factory (Bitmap/Memory / Pen dispatch) | BITMAPS.C, DALLOC.C; CURBRUSH.C |
| 19 | Creational | Singleton / Monostate | PRISM.C |
| 20–21 | Creational | Prototype (Bitmap clone / Undo swap) | BITMAPS.C; MAINMAG.C |
| 22–28 | Architectural | Code Overlay; Two-Buffer Undo; Per-Object Save-Under; Cooperative Resource Sharing; Hardware Register Abstraction; Graphics Context Stack; Service Locator (IPC) | PRISM.txt/.H; MAINMAG.C, MAGWIN.C; BMOB.C; PRISM.C, DPIO.C; PRISM.H; PGRAPH.C; HOOK.C, DPHOOK.H |

---

## Obtaining the source code

The Deluxe Paint V1 source code is the property of Electronic Arts and is **not redistributed here**, in compliance with the terms of its release. It was released by EA to the Computer History Museum in 2015 and can be obtained from:

https://computerhistory.org/blog/electronic-arts-deluxepaint-early-source-code/

`verify_patterns.py` takes the path to the extracted source directory as its argument. The analysis notebook runs entirely from the shipped CSV exports and does not need the source.

---

## Recompilation artefacts

The paper also reports recompiling the source with SAS/C v6.58. The recompilation diff and the hard-disk file (HDF) of the build environment are **not** included here, in compliance with the licence terms of the Deluxe Paint release and of the Amiga Kickstart (ROM), Amiga Workbench (OS), and SAS/C compiler. They are available on request to the first author.

---

## Licence

The verification script and analysis notebook in this repository are released as supplementary material to the paper. The Deluxe Paint V1 source code is the property of Electronic Arts and is not part of this repository. The metric CSV exports are derived measurements (file and function names with their computed metrics) and contain no Deluxe Paint source code.
