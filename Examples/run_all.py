"""
Executes every example notebook in place, so that the saved outputs are up to
date. Needs papermodels >= 0.21 (see the README in this directory).

    uv run python Examples/run_all.py [Example_1 ...]
"""

import pathlib
import sys

import nbformat
from nbconvert.preprocessors import CellExecutionError, ExecutePreprocessor

HERE = pathlib.Path(__file__).parent
# Examples that are expected to stop with an error; the notebook is saved up to
# and including the error. See the notebook for the reason.
EXPECTED_ERRORS = set()


def run(path: pathlib.Path) -> bool:
    notebook = nbformat.read(path, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs, cell.execution_count = [], None
    executor = ExecutePreprocessor(timeout=600)
    try:
        executor.preprocess(notebook, {"metadata": {"path": str(path.parent)}})
    except CellExecutionError as error:
        if path.stem not in EXPECTED_ERRORS:
            print(f"FAILED {path.stem}\n{error}")
            return False
        nbformat.write(notebook, path)
        print(f"{path.stem}: stopped at the expected error")
        return True
    nbformat.write(notebook, path)
    print(f"{path.stem}: ok")
    return True


if __name__ == "__main__":
    selected = set(sys.argv[1:])
    paths = sorted(HERE.glob("Example */Example_*.ipynb"))
    results = [run(path) for path in paths if not selected or path.stem in selected]
    sys.exit(0 if all(results) else 1)
