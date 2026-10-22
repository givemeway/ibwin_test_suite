# idevsutil QA Console - modular structure

## Structure
```text
idevsutil_qa_package/
├── main.py
├── builds.json                 # keep beside main.py / working directory
└── idevsutil_qa/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── config.py
    ├── console.py
    ├── models.py
    ├── utils.py
    ├── core/
    │   ├── __init__.py
    │   └── idevsutil.py
    └── suites/
        ├── __init__.py
        ├── regression.py
        └── search.py
```

## Imports
`search.py` imports the command class with:
```python
from ..core.idevsutil import IdevsUtil
```
`console.py` imports suites with:
```python
from .suites.regression import Regression
from .suites.search import SearchSuite
```

## Run
From this folder:
```bash
python main.py --user YOUR_USER --server YOUR_SERVER --password YOUR_PASSWORD --dedup 1
```
Or:
```bash
python -m idevsutil_qa --user YOUR_USER --server YOUR_SERVER --password YOUR_PASSWORD --dedup 1
```

Keep `builds.json` in the directory from which the application expects it, or change `load_builds("builds.json")` later to use a path relative to the project.
