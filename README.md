# EXFOR Web API Python Client (`exfor_client.py`)

A lightweight Python client and CLI for interacting with the [EXFOR Web API](https://nds.iaea.org/exfor/x4guide/API/).
This tool enables searching, retrieving, and parsing experimental nuclear data — including uncertainties, covariance information, and metadata — while preserving provenance.

It supports the **C4**, **C5**, and **C5M** formats, allowing for automated analysis of experimental datasets and uncertainty propagation.

---

## 📦 Contents

* [`exfor_client.py`](./exfor_client.py) — Python module + command-line interface
* [`README.md`](./README.md) — This documentation

---

## 🧭 Overview

### Features

* Search datasets via the **x4list** endpoint
* Retrieve and parse datasets in **CSV**, **C4**, **C5**, and **C5M** formats
* Extract data, uncertainties, and metadata for each dataset
* Download covariance matrices and correlation coefficients (C5M)
* Perform batched bulk downloads across multiple datasets
* Retrieve full EXFOR **Entry/Subentry** records
* Safe HTTP handling with timeouts and retries

---

## ⚙️ Requirements

| Dependency            | Purpose       | Installation           |
| --------------------- | ------------- | ---------------------- |
| Python ≥ 3.9          | Runtime       | —                      |
| `requests`            | HTTP requests | `pip install requests` |
| `pandas` *(optional)* | CSV parsing   | `pip install pandas`   |

---

## 🚀 Command Line Interface (CLI)

Run:

```bash
python exfor_client.py <subcommand> [options]
```

### Subcommands

#### 🔍 `search`

Search for datasets using the **x4list** endpoint.

```bash
python exfor_client.py search --target PB-204 --reaction n,g --quantity SIG --output json
```

**Options**

| Option       | Description                                              |
| ------------ | -------------------------------------------------------- |
| `--target`   | Target isotope (e.g. `PB-204`, `PB-*`)                   |
| `--reaction` | Reaction type (e.g. `n,g`, `n,*`)                        |
| `--quantity` | Quantity code (`SIG`, `DA`, `DE`, `NU`, `FY`)            |
| `--output`   | Format: `json`, `xml`, `csv`, or `txt` *(default: json)* |
| `--extra`    | Additional filters as `key=value`                        |

---

#### 💾 `download`

Download a single dataset using **x4get**.

```bash
python exfor_client.py download --dataset 11679024 --format csv --plus 1 --out 11679024.csv
```

**Options**

| Option      | Description                                                 |
| ----------- | ----------------------------------------------------------- |
| `--dataset` | EXFOR DatasetID                                             |
| `--format`  | `csv`, `c4`, `c5`, `c5a`, `c5m`, or `c5ma` *(default: csv)* |
| `--plus`    | CSV mode: `1` (computational), `2` (universal)              |
| `--out`     | Output filepath (stdout if omitted)                         |

---

#### 📦 `bulk`

Perform a one-step batch retrieval via **x4dat**.

```bash
python exfor_client.py bulk --target Zn-64 --reaction n,p --quantity SIG --op c4 --out zn64_np_sig.c4
```

**Options**

| Option                                 | Description                                                   |
| -------------------------------------- | ------------------------------------------------------------- |
| `--target`, `--reaction`, `--quantity` | Search filters                                                |
| `--op`                                 | Output type: `c4`, `c5`, `c5a`, `c5m`, `c5ma` *(default: c4)* |
| `--extra`                              | Additional key=value filters                                  |
| `--out`                                | Output filepath                                               |

---

#### 🧾 `entry`

Retrieve a full Entry/Subentry via **x4get**.

```bash
python exfor_client.py entry --sub A1495003 --plus 6 --out A1495003.csv
```

**Options**

| Option   | Description                                   |
| -------- | --------------------------------------------- |
| `--sub`  | Entry (`A1495`) or Subentry (`A1495003`)      |
| `--plus` | `5` = X5 JSON, `6` = CSV, omitted = raw EXFOR |
| `--out`  | Output filepath                               |

---

## 🧩 Programmatic Usage

```python
from exfor_client import (
    search_datasets, download_dataset_csv, download_dataset_c4,
    download_dataset_c5, bulk_download, get_entry_or_subentry,
    extract_xy_from_csv_rows,
    get_dataset_covariance_and_metadata, download_dataset_c5m,
)

# 1) Search datasets
lst = search_datasets(target="PB-204", reaction="n,g", quantity="SIG", output="json")
print(len(lst.get("x4Datasets", [])), "datasets found")

# 2) Download a dataset as CSV
rows, df = download_dataset_csv("11679024", plus=1)

# 3) Retrieve C4 or C5 data
c4_text = download_dataset_c4("11679024")
c5m_text = download_dataset_c5("23114002", op="c5m")

# 4) Parse covariance and metadata
info = get_dataset_covariance_and_metadata("23114002")
meta = info["metadata"]
cov  = info["covariance"]

# 5) Entry/Subentry retrieval
entry_csv = get_entry_or_subentry("A1495003", plus=6)
```

---

## 📊 Covariance and Metadata (C5M)

Some datasets provide a **C5M** format with detailed metadata and covariance data.

**Metadata fields**:

* `TITLE`, `AUTHORS`, `INSTITUTE`, `METHOD`, `REACTION`, `MF`, `MT`, `PROJ`, `TARGET`, `PRODUCT`, etc.

**Covariance block includes**:

* `E_min`, `E_max` — Energy interval per point
* `data` — Observable values
* `std_pct` — Percent standard deviation
* `sigma` — Absolute deviation
* `corr` — Correlation matrix
* `cov` — Covariance matrix

> Use `get_dataset_covariance_and_metadata(dataset_id)` to retrieve and parse both metadata and covariance in one step.

---

## 📁 CSV Modes

| Mode     | Description           | Example Columns                       |
| -------- | --------------------- | ------------------------------------- |
| `plus=1` | **Computational CSV** | `DATA (B)`, `DATA-ERR (B)`, `EN (EV)` |
| `plus=2` | **Universal CSV**     | `y`, `dy`, `x2(eV)`                   |

---

## 🧮 Formats

| Format   | Description                                      |
| -------- | ------------------------------------------------ |
| **C4**   | Compact numeric data (ideal for analysis)        |
| **C5**   | Extended data with metadata                      |
| **C5A**  | Auto-renormalized C5                             |
| **C5M**  | Includes correlation matrix and covariance block |
| **C5MA** | Auto-renormalized with covariance                |

---

## 🧠 Best Practices

* Keep **statistical** vs **systematic** uncertainties distinct (`ERR-S`, `ERR-SYS`, `dy`).
* Always record **units** (`EN (EV)`, `DATA (B)`).
* Preserve **provenance**: dataset ID, author, year, and Subentry info.
* Examine **C5M COMMENT/ALGORITHM** lines for details on covariance generation.

---

## 🔧 Notes and Limitations

* Generic C5 parsing (non-C5M) is not yet implemented.
* Only IAEA EXFOR API is supported (NNDC/JANIS not included).
* No local renormalization — use server-side C5A/C5MA.

---

## 🧭 Etiquette

* Use **`x4dat`** for bulk retrieval instead of many single calls.
* Avoid rapid, repeated API hits.
* Handle network errors gracefully; client includes simple retries and timeouts.

---

## 📚 References

* [EXFOR Web API Documentation](https://nds.iaea.org/exfor/x4guide/API/)
* NDS 120 (2014) 272 — *EXFOR Reference Paper*
* NIM A 888 (2018) 31 — *EXFOR Web Database & Tools*

---

