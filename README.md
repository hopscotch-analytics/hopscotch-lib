# hopscotch-analytics

Interactive clickstream analysis for Jupyter notebooks, VS Code, and Google Colab.

[![PyPI](https://img.shields.io/pypi/v/hopscotch-analytics)](https://pypi.org/project/hopscotch-analytics/)
[![Python](https://img.shields.io/pypi/pyversions/hopscotch-analytics)](https://pypi.org/project/hopscotch-analytics/)

---

## What it does

hopscotch-analytics turns raw event data into interactive visualizations directly inside your notebook. Explore user journeys, build funnels, compare segments, and cluster paths — all without leaving the notebook.

| Widget | What you get |
|--------|-------------|
| `es.transition_graph()` | Interactive directed graph of event transitions |
| `es.step_sankey()` | Step-by-step Sankey diagram of path positions |
| `es.funnel()` | Conversion funnel with step-by-step drop-off |
| `es.segment_overview()` | Heatmap of metrics across segment values |
| `es.cluster_analysis()` | Unsupervised path clustering with k-means or HDBSCAN |

## Installation

```bash
pip install hopscotch-analytics
```

## Quick start

```python
import pandas as pd
from hopscotch import Eventstream

df = pd.read_csv("events.csv")  # columns: user_id, event, timestamp
es = Eventstream(df)

es.transition_graph()
```

No arguments required — configure everything interactively in the widget sidebar.

### Sample dataset

```python
from hopscotch.datasets.ecom import load_ecom
from hopscotch import Eventstream

df = load_ecom()
es = Eventstream(df, _schema={
    "path_cols": ["user_id"],
    "segment_cols": ["platform", "acquisition_channel"],
})

es.funnel(steps=["catalog", "add_to_cart", "checkout", "purchase"])
```

## Documentation

Full documentation at **[hopscotch-analytics.com/docs](https://hopscotch-analytics.com/docs)**

## Part of the Hopscotch ecosystem

This library is part of [Hopscotch](https://hopscotch-analytics.com) — a clickstream analytics platform for product teams. The library and the platform share the same analytical models, so findings from a notebook translate directly to the platform.
