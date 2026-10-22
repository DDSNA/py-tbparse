# Spec A1: `errors.py`, the error categories and `exit_code_for` (no behaviour change)

Track: 0.6.0 exit codes and errors. Plan: [plan-0.6.0-exit-codes-and-errors.md](../plan-0.6.0-exit-codes-and-errors.md), section 5 and WP1. Issues: #186, #127. Read the plan's sections 2 and 5 first. Common rules: [README.md](README.md#common-rules-for-every-spec) (follow the agent rules file).

- Branch: `feat/errors-module`
- PR title: `errors.py: one module for the error categories and their exit codes (WP1 of the 0.6.0 plan)`
- PR body starts with: `Refs #186, refs #127`
- Depends on: nothing. Next: A2.

## Goal

Add the error categories and the code that maps an exception to an exit code, without changing what any command returns, prints or raises. Later packages use them.

## Owner decisions this builds on (do not reopen)

- Exit codes (2026-10-16): 0 ok, 1 finding, 2 usage, 3 crash, 4 bad input, 5 refused, 6 integrity, 7 partial. All in 0.6.0; nothing of this ships in a 0.5.x patch.
- No `E001`-style codes in messages, no required `code=`/`context=` constructor arguments (plan section 5; read as adopted with the scheme).

## Files to touch (read on `main` at `1130fa9`)

| File | Change |
| --- | --- |
| `py_tbparse/errors.py` (new) | everything below |
| `py_tbparse/_xml.py` | remove the body of `class PyTbparseError(ValueError)` (line ~60) and import it instead: `from .errors import PyTbparseError`. `PackageTooLargeError(PyTbparseError)` stays in `_xml.py`. |
| `py_tbparse/__init__.py` | keep `from ._xml import PyTbparseError, ...` working (it does, through the re-export) and add the new public names to the import and to `__all__` |
| `docs/api.md` | one bullet per new public name (see "Public names"), and update the existing `PyTbparseError` bullet to say where the categories are |
| `AGENTS.md` | new row for `errors.py` in "Non-R modules"; in the `_xml.py` row replace "Also defines `PyTbparseError(ValueError)`..." with "re-exports `PyTbparseError` from `errors.py`" and keep the rest of the sentence's rules |
| `tests/test_errors.py` (new) | tests below |

`errors.py` must import nothing from the rest of the package (other modules import it; a cycle would break the import). It may import `json`, `zipfile`, `enum`, and `lxml.etree` and `pandas.errors` lazily or at top level (both are hard dependencies).

## Interfaces

```python
# py_tbparse/errors.py
from __future__ import annotations
import enum, json, zipfile

class ExitCode(enum.IntEnum):
    OK = 0
    FINDING = 1
    USAGE = 2
    CRASH = 3
    BAD_INPUT = 4
    REFUSED = 5
    INTEGRITY = 6
    PARTIAL = 7

PRECEDENCE: tuple[ExitCode, ...] = (ExitCode.CRASH, ExitCode.USAGE, ExitCode.BAD_INPUT, ExitCode.REFUSED,
                                    ExitCode.INTEGRITY, ExitCode.PARTIAL, ExitCode.FINDING, ExitCode.OK)

class PyTbparseError(ValueError): ...          # moved here, same docstring idea (see below)
class UsageError(PyTbparseError): ...          # exit 2: a bad argument value, known without opening a file
class InputError(PyTbparseError): ...          # exit 4: a file, or a name in it, cannot be used
class RefusedError(PyTbparseError): ...        # exit 5: declined on purpose, nothing written
class OutputRefusedError(RefusedError, FileExistsError): ...   # exit 5: the output exists or is an input
class IntegrityError(PyTbparseError): ...      # exit 6: the result has, or would have, broken references

def exit_code_for(exc: BaseException) -> int: ...
def first_by_precedence(codes) -> int: ...     # used by the pre-commit wrapper in A8; 0 for an empty iterable
```

`exit_code_for` checks in this order and returns the first match (plan section 5):

1. `UsageError` -> 2
2. `RefusedError` -> 5 (this also catches `OutputRefusedError`, which is an `OSError` too, so this check must come before the `OSError` one)
3. `IntegrityError` -> 6
4. any other `PyTbparseError` -> 4
5. `FileNotFoundError`, `IsADirectoryError`, `PermissionError`, any other `OSError`, `zipfile.BadZipFile`, `json.JSONDecodeError`, `lxml.etree.XMLSyntaxError`, `pandas.errors.ParserError` -> 4
6. everything else (`KeyError`, `RuntimeError`, a plain `ValueError`, `TypeError`, ...) -> 3

Note `json.JSONDecodeError` is a `ValueError` and `pandas.errors.ParserError` is a `ValueError`: they must be matched by their own class before falling to step 6. A plain `FileExistsError` (not yet converted; A2 converts them) is an `OSError` and maps to 4 here; that is expected until A2.

`first_by_precedence(codes)`: returns the code from `codes` that comes first in `PRECEDENCE`; a code that is not in `ExitCode` (for example argparse's 2 is fine, but a stray 9) counts as `CRASH`. Empty input -> 0.

Docstrings: each class gets one line saying what it means and its exit code; `PyTbparseError` keeps the meaning of today's docstring in `_xml.py` (a `ValueError` on purpose, messages unchanged, no error codes) and adds "the subclasses in this module say which exit code the command line gives".

## Public names

Add to `__init__.py` and `__all__`: `UsageError`, `InputError`, `RefusedError`, `OutputRefusedError`, `IntegrityError`, `ExitCode`, `exit_code_for`. Do **not** export `PRECEDENCE` or `first_by_precedence` (internal; the wrapper imports them from `py_tbparse.errors`). Each exported name needs a `docs/api.md` bullet; put them in the section that lists `PyTbparseError` (search the page for it).

## Behaviour with examples

```python
>>> from py_tbparse import OutputRefusedError, exit_code_for, PyTbparseError
>>> e = OutputRefusedError("refusing to overwrite existing file: out.twb")
>>> isinstance(e, FileExistsError), isinstance(e, ValueError), isinstance(e, PyTbparseError)
(True, True, True)
>>> str(e), e.args
('refusing to overwrite existing file: out.twb', ('refusing to overwrite existing file: out.twb',))
>>> exit_code_for(e), exit_code_for(KeyError("x")), exit_code_for(ValueError("x"))
(5, 3, 3)
```

Checked once in the shared venv (Python 3.13.5) while writing this spec: a class with parents (subclass of `ValueError`, `FileExistsError`) can be created, is caught by `except FileExistsError`, `except ValueError`, `except OSError` and by its own base, keeps `str(e)` and `e.args`, has `errno`/`strerror`/`filename` of `None`, and survives a `pickle` round trip with the same type and message. Not checked on Python 3.9 (CI runs 3.9): the tests below run there.

## Edge cases

- `OutputRefusedError("a", "b")` with two arguments: `OSError` treats two arguments as `(errno, strerror)`. Nobody calls it that way; the test pins the one-argument form only. Do not add a custom `__init__`.
- `exit_code_for(SystemExit(2))` and `KeyboardInterrupt`: not exceptions the CLI catches; the function may return 3 for them, but A4 must never call it for them. Add no special case.
- `exit_code_for` on a subclass with two category parents (A3 creates `SliceIntegrityError(SliceError, IntegrityError)`): the order above decides; integrity beats the generic `PyTbparseError` 4. Test it with a local two-parent class.

## Tests to add (`tests/test_errors.py`)

- `test_base_is_the_same_object_everywhere`: `py_tbparse.PyTbparseError is py_tbparse._xml.PyTbparseError is py_tbparse.errors.PyTbparseError`.
- `test_categories_are_pytbparse_errors_and_value_errors`: each of the five category classes is a subclass of `PyTbparseError` and `ValueError`.
- `test_output_refused_is_caught_by_every_old_handler`: raise and catch with `FileExistsError`, `ValueError`, `OSError`, `PyTbparseError`, `RefusedError`.
- `test_pickle_round_trip_keeps_type_and_message` (parametrised over the six classes): `pickle.loads(pickle.dumps(e))` has the same type, `str`, `args`.
- `test_exit_code_for_each_class` (parametrised): the documented code for one instance of each category class.
- `test_exit_code_for_builtins` (parametrised): `FileNotFoundError`, `IsADirectoryError`, `PermissionError`, `OSError`, `zipfile.BadZipFile`, `json.JSONDecodeError("x", "", 0)`, an `lxml.etree.XMLSyntaxError` obtained by parsing `b"<a>"`, `pandas.errors.ParserError` -> 4.
- `test_exit_code_for_unknown_is_crash`: `KeyError`, `RuntimeError`, plain `ValueError`, `TypeError` -> 3.
- `test_two_parent_subclass_takes_the_category_code`: with a local `class Feat(PyTbparseError)`, `class X(Feat, IntegrityError)` gives 6 and `class Y(Feat, RefusedError)` gives 5, while `Feat` alone gives 4. (Put the feature class first and the category second; `class Z(PyTbparseError, IntegrityError)` is an MRO error.)
- `test_first_by_precedence`: `[]` -> 0; `[1, 0]` -> 1; `[7, 1]` -> 7; `[4, 3]` -> 3; `[2, 4]` -> 2; `[9]` -> 3.
- `test_exit_code_enum_values`: the enum has exactly the eight names and values above.

The existing `tests/test_error_base.py` and `tests/test_api_doc.py` must pass unchanged (the walk will find the new classes; they all derive from `PyTbparseError`).

## Docs

- `docs/api.md`: bullets as above. One sentence under them: "The command line turns these into exit codes from 0.6.0 (see docs/cli.md); until then exit codes are unchanged."
- `AGENTS.md`: the module row (what the module holds, "imports nothing from the package", the order of `exit_code_for`, "new deliberate errors derive from one of the categories when the CLI must give a code other than 4").
- Nothing in `docs/cli.md` changes in this package.

## How to verify

```bash
PYTHONPATH=$PWD /home/claude-user/ai-sandbox/py-tbparse/.venv/bin/pytest -q tests/test_errors.py tests/test_error_base.py tests/test_api_doc.py tests/test_exit_codes.py
```

then the whole non-browser suite (README, rule 8): it must pass with no test changed except the new file.

## Not verifiable here

Nothing to check in Tableau. Python 3.9 behaviour of the two-parent class is checked only by CI.

## Risks

- Import cycle: `errors.py` must not import from `py_tbparse`. If `_xml.py` is imported first, it imports `errors.py`; that is fine.
- `inspect.getdoc` in `test_api_doc.py` requires a docstring on every public name: write them.
- If the two-parent class misbehaves on 3.9 in CI, stop and report (the plan's fallback, `RefusedError` without `FileExistsError`, changes A2's size; the owner should know).

## Definition of done

New module and tests in, all existing tests unchanged and green locally and in CI (all jobs including Windows and 3.9), `docs/api.md` and `AGENTS.md` updated, no change to any command's output or exit code, no version bump.
