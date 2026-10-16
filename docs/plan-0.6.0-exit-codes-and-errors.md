# Plan for 0.6.0: distinct exit codes (#127) and one error hierarchy (#186)

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). This is a plan, not a change: no code is touched by the pull request that adds this page. It was written against `main` at 1fa6acd. The numbers of raise sites below come from `grep` on that commit; the exit codes of "today" come from [cli.md](cli.md#exit-codes), checked against `py_tbparse/cli.py`. Nothing here was run against Tableau Desktop, and the new scheme itself is not implemented or tested.

Owner decision for #127 (2026-10-16): 0.6.0 adopts **distinct exit codes per meaning**, **2 means a usage error only**, and the change is breaking and goes into the 0.6.0 release notes. #186 is planned together with it because the cheapest way to pick the right exit code is to look at the class of the exception.

Where this page chooses between two reasonable options it says "Choice:" and names the alternative. Anything the owner has to confirm is repeated under [Open questions](#open-questions).

## 1. Current state

### Exit codes today

The full per-command table is in [cli.md](cli.md#exit-codes) and is pinned by `tests/test_exit_codes.py` (one case per row). The short version:

| Code | What it means today | Where |
| --- | --- | --- |
| 0 | success; also "no finding at `--fail-on`" | everywhere |
| 1 | an error (most commands) | table commands, `diff`, `batch`, `rename`, `library`, `style`, `scaffold`, `template` (except `check`, `drift`), `sheet copy`, `dashboard copy` |
| 1 | a finding at `--fail-on` | `audit`, `template check`, `template drift` |
| 1 | "the two files differ" | `diff-xml` |
| 1 | "some file was not written" | `template apply-folder` |
| 1 | a problem found by `check` (an unreadable file counts too) | `style check` |
| 1 | a Python exception nobody catches (traceback; not designed) | unwritable `-o`, a malformed `.twb` given to table commands, `validate` or `diff` |
| 2 | any error at all | `sanitize`, `prune`, `slice`, `docs`/`dictionary` |
| 2 | input cannot be read, or a bad option value | `audit`, `template check`, `template drift`, `diff-xml` |
| 2 | a finding: a relationship is broken | `validate` |
| 2 | partial result, the rest was written | `sheet copy`, `dashboard copy`, `library import --write`, `style export`, `style import` |
| 2 | slice dry run predicts that `--write` would be refused | `slice` |
| 2 | argparse usage error (`--help` is 0) | every command |
| 3 | a rule crashed (a bug in py-tbparse) | `audit`, `template check`, `template drift` only |

So 1 means five things, 2 means six, and 3 exists in three commands. `python -m py_tbparse.precommit` returns the numerically largest code of its files (`max`), which only makes sense while a bigger number means "worse".

### Error classes today

`PyTbparseError(ValueError)` already exists in `py_tbparse/_xml.py` and is exported from the package (documented in [api.md](api.md)). These derive from it: `SliceError`, `ScaffoldError`, `SanitizeError`, `SheetCopyError` (and `SheetCopyAbort` under it), `StyleError`, `TemplateError` (and `SheetMissing`, `SheetEmpty` under it), `LibraryError`, `PruneError`, `PackageTooLargeError`. Dashboard copy raises `SheetCopyError`; there is no `DashboardCopyError` in the code although #186 lists one.

Not using it, counted on `main`:

- 77 `raise ValueError(...)`: 39 in `webgui.py`, 38 in the rest of the library.
- 24 `raise FileExistsError(...)`, all of the form "refusing to overwrite ...".
- Built-ins that are raised or caught on purpose: `FileNotFoundError` (13 sites), `zipfile.BadZipFile`, `json.JSONDecodeError`, `lxml.etree.XMLSyntaxError`, `pandas.errors.ParserError`, `OSError`. The CLI catches them by hand: `_WORKBOOK_ERRORS` in `cli.py` is one tuple, but `_run_template`, `_run_library`, `_run_style`, `_run_scaffold`, `_run_rename` and `_run_template_drift` each carry a different copy of the list.

Consequence for #127: the CLI cannot tell "bad option value" from "unreadable input" from "refused to overwrite", because they are all `ValueError` or `FileExistsError` and are caught in one `except`. The exit code is chosen by the `except` clause position, not by what happened.

## 2. Proposed exit codes

Start from the issue (0 ok, 1 findings or partial, 2 usage or unreadable, 3 crash). Three things in it do not survive the owner's decision: "partial" shares 1 with "findings", "unreadable" shares 2 with "usage", and the issue puts integrity and refused writes nowhere. The scheme keeps the issue's 0, 1, 2 and 3 where it can, and adds 4 to 7:

| Code | Name | Meaning | Who may return it |
| --- | --- | --- | --- |
| 0 | ok | The command did what was asked. A dry run is 0. A check with nothing at `--fail-on` is 0. | all |
| 1 | finding | The command ran and its answer is "not clean": a finding at or above `--fail-on`, two files that differ, `style check` problems. Commands that have no verdict never return 1. | `audit`, `template check`, `template drift`, `diff-xml`, `style check` |
| 2 | usage | The command line is wrong, and could be known to be wrong without opening any file: unknown option, missing argument, bad choice, option combinations (`ap.error`), a malformed `--param`/`--token`/`--column`, an unknown rule id in `--only`/`--skip`, a number out of range (`--cutoff`, `--min-mapped`). `--help` stays 0. | all |
| 3 | crash | py-tbparse itself failed: a rule crashed, or an exception nobody expected escaped. Traceback on stderr. | all |
| 4 | bad input | An input file or a name inside it cannot be used: not found, not readable, not a zip, malformed XML or JSON, wrong file type, unknown dashboard or sheet name, mapping file with missing columns. Also an output that cannot be written for an operating-system reason (no folder, no permission); the message says which. | all |
| 5 | refused | py-tbparse declined on purpose and wrote nothing: the output exists without `--overwrite`, the output is one of the inputs, `--on-clash fail` met a clash, `--strict` would drop something, nothing is copyable. | writers |
| 6 | integrity | The workbook has, or the result would have, broken references: `validate` found a broken relationship; `slice` (also a dry run, which predicts it) finds new integrity problems in its result. | `validate`, `slice` |
| 7 | partial | The run finished and wrote what it could, but some part was refused or failed. The others are written. | `sheet copy`, `dashboard copy`, `library import`, `style export`, `style import`, `template apply-folder` |

Numbers 8 and up are not used and stay free. 64 to 78 (the BSD `sysexits.h` range) and 126 to 255 (shell, signals) are avoided on purpose.

**Choice: 3 stays "crash", and the new meanings take 4 to 7.** The alternative is to follow the issue's 3 = unreadable and move the crash to a high number. This plan keeps 3 because `audit`, `template check` and `template drift` already return it for a crash and `ci.md` tells users that "exit 3 if py-tbparse itself failed"; changing it would break the one code that is already clean. It also lets an unexpected exception (today a traceback with exit 1) get a designed code in every command. The price is that "unreadable" is 4, not 3 as the issue sketched.

**Choice: `validate` finding broken relationships is 6, not 1.** The alternative is 1 ("a finding", like `audit`, whose `V001`/`V002` ids already look like findings in the CI formats). Reason for 6: today `validate` returns 1 for "cannot load the workbook". If 1 became "broken relationship", an old script that treats `validate` 1 as an infrastructure problem would silently flip meaning, and the owner asked for integrity to be separate. With 6 a script that still tests for 2 or 1 fails loudly in a different way. The cost is that `audit` and `validate` differ for the same kind of question; the alternative is cheap to switch to (one constant) if the owner prefers it.

**Choice: an unknown dashboard, sheet or datasource name is 4, not 2.** It is a command-line value, but py-tbparse only finds out by opening the file. The rule for 2 is "knowable without opening a file". The alternative is to treat every wrong value as 2.

**Choice: `apply-folder` where nothing is written is still 7.** The alternative is 4 when every file failed. It keeps the rule simple: 7 means "the run finished but not every file was written".

**Choice: when several codes could apply, the first of this list wins:** 3, 2, 4, 5, 6, 7, 1, 0. The list matters for the pre-commit wrapper (section 3) and for commands that find two things at once (a clash and a broken input is 4, because the input came first). A numeric `max` is no longer right because 3 is not the worst after 4 to 7 exist.

Inconsistencies in today's behaviour that the scheme fixes rather than copies:

- an uncaught exception ends with traceback and exit 1: becomes 3 (or 4 for the known unreadable-input and unwritable-output cases, which get caught);
- a `slice` dry run reports a predicted refusal as 2 although a dry run is otherwise "done" (0): becomes 6, so a dry run and the real run agree;
- `style import` as a dry run returns 1 for a clash under `--on-clash fail` while `library import` as a dry run returns 0 with entries that cannot be imported: see Open questions;
- `style check` counts an unreadable file as "a problem" (1): becomes 4;
- `template drift` and `template check` return 2 for "no file matches" and "bad option" alike: 4 and 2.

## 3. Old to new, per command

Rows follow the table in [cli.md](cli.md#exit-codes). A dash means the code was not used and stays unused.

| Command | Case | Old | New |
| --- | --- | --- | --- |
| `WORKBOOK [TABLE]`, `tables`, `graph` | printed | 0 | 0 |
| | workbook not found, `ValueError` from the parser, malformed `.twb`/`.twbx` (uncaught today) | 1 | 4 |
| | `-o` unwritable (uncaught today) | 1 | 4 |
| | unknown table, a CI format on a plain table, bad option | 2 | 2 |
| `WORKBOOK validate` | all relationships resolve | 0 | 0 |
| | a relationship is broken (V001, V002), any `--format` | 2 | 6 |
| | workbook cannot be loaded | 1 | 4 |
| `diff A B` | printed, also when the two differ | 0 | 0 |
| | a workbook not found or invalid | 1 | 4 |
| `diff-xml A B` | no differences | 0 | 0 |
| | differences | 1 | 1 |
| | a file cannot be read | 2 | 4 |
| | `-o` names one of the inputs | 2 | 5 |
| | usage error | 2 | 2 |
| `batch DIR` | `DIR` is not a directory | 1 | 4 |
| `rename` (also `--missing`, `--apply`, `--write-workbook`) | done | 0 | 0 |
| | workbook, reference or mapping unreadable or invalid | 1 | 4 |
| | output exists, or is an input | 1 | 5 |
| | `--cutoff` outside 0..1 | 1 | 2 |
| | `--missing` without `--reference`, `--missing` with `--apply` | 2 | 2 |
| `audit` | no finding at `--fail-on` | 0 | 0 |
| | finding at or above `--fail-on` | 1 | 1 |
| | workbook cannot be read | 2 | 4 |
| | bad `--only`/`--skip` | 2 | 2 |
| | a rule crashed | 3 | 3 |
| `template check` | same five cases as `audit` (template not a `.twbx` template or malformed manifest is 4) | 0 / 1 / 2 / 3 | 0 / 1 / 4 or 2 / 3 |
| `template drift` | same; template, answers or data unreadable, or no file matches | 2 | 4 |
| `template make`, `show`, `targets`, `target-make`, `update`, `apply` | done, or a dry run | 0 | 0 |
| | `TemplateError` and other invalid input, missing file, bad zip or JSON | 1 | 4 |
| | existing output, or output is an input | 1 | 5 |
| | malformed `--param`/`--token`/`--column`, `--output` without `--markdown`, `--table` missing | 2 | 2 |
| `template apply-folder` | every file written | 0 | 0 |
| | some file skipped or failed | 1 | 7 |
| | an error before the run (template unreadable, summary exists) | 1 | 4 / 5 |
| `library export`, `show` | done | 0 | 0 |
| | any error | 1 | 4 (output exists: 5) |
| `library import` | done, or a dry run | 0 | 0 |
| | `--on-clash fail` meets a clash | 1 | 5 |
| | other error | 1 | 4 (output exists: 5) |
| | with `--write`: some entry failed or was skipped as a dependent | 2 | 7 |
| `style show` | done / error | 0 / 1 | 0 / 4 |
| `style check` | no problem | 0 | 0 |
| | a problem found | 1 | 1 |
| | file unreadable | 1 | 4 |
| `style export`, `import` | done | 0 | 0 |
| | any error | 1 | 4 (output exists: 5) |
| | dry run of `import` where a palette name clashes under `--on-clash fail` | 1 | 5 |
| | some palette was invalid; the others are written | 2 | 7 |
| `scaffold make`, `show`, `apply` | done | 0 | 0 |
| | any error | 1 | 4 (output exists: 5) |
| `sanitize IN OUT` | written | 0 | 0 |
| | input unreadable | 2 | 4 |
| | `OUT` exists without `--overwrite`, or is `IN` | 2 | 5 |
| | unknown `--keep`, bad output extension, usage error | 2 | 2 |
| `prune WORKBOOK` | done, dry run or `--write -o OUT` | 0 | 0 |
| | unreadable workbook | 2 | 4 |
| | output refused (exists, is the input) | 2 | 5 |
| | bad extension, usage error | 2 | 2 |
| `slice WORKBOOK` | done, dry run or `--write -o OUT` | 0 | 0 |
| | unreadable workbook, unknown dashboard | 2 | 4 |
| | `--strict` would drop something, output refused | 2 | 5 |
| | the result has new integrity problems, with `--write` (nothing written) | 2 | 6 |
| | the same found by a dry run (the dry run predicts the refusal) | 2 | 6 |
| | usage error | 2 | 2 |
| `sheet copy SRC --to TARGET` | done, or a dry run | 0 | 0 |
| | unreadable file, no sheet found in the source | 1 | 4 |
| | clash under `--on-clash fail`, `--strict` refusal, nothing copyable, output refused | 1 | 5 |
| | some sheet was refused; the others are copied | 2 | 7 |
| `dashboard copy SRC --to TARGET` | same as `sheet copy` | 0 / 1 / 2 | 0 / 4 / 5 / 7 |
| `docs`, `dictionary` | written or printed | 0 | 0 |
| | workbook cannot be read | 2 | 4 |
| | `-o` is the workbook itself | 2 | 5 |
| | usage error | 2 | 2 |
| any command | an exception that nobody expected | 1 (traceback) | 3 |

### The pre-commit wrapper

`python -m py_tbparse.precommit audit|validate|template-check FILE...` runs the command once per file and today returns `max(codes)`. New behaviour:

- It returns the code that comes first in the precedence list of section 2 (3, 2, 4, 5, 6, 7, 1, 0) over all files. pre-commit itself only looks at zero or non-zero, so hook users see no difference; scripts that read the code do.
- Its own errors (no arguments, unknown hook command) stay 2: they are usage errors.
- The `SystemExit` branch (argparse, `e.code` of 2) stays and still counts as usage.
- The hook's comment in `.pre-commit-hooks.yaml` ("1 a finding, 2 unreadable file or bad option, 3 a rule crashed") and the line in `ci.md` change to the new meanings. The module docstring says "0 to 3"; it changes to "0 to 7".
- Unknown file types are ignored as today; a hook that is given zero files returns 0.
- Which files count as a file argument (suffix `.twb`/`.twbx`) is not touched.

## 4. Migration note for CI users

This text goes into the 0.6.0 release notes (and a short form into [ci.md](ci.md)):

> **Breaking: exit codes.** 2 now means only that the command line is wrong. Every other failure has its own code, written once in [docs/cli.md](cli.md#exit-codes): 1 finding or difference, 3 crash, 4 bad input, 5 refused (nothing written), 6 integrity problem, 7 partial result. Commands that have no verdict (such as `rename`, `library`, `scaffold`, `sanitize`) no longer return 1.
>
> What to change in a script:
> - `audit`, `template check`, `template drift`, `diff-xml`: 0, 1 and 3 mean what they meant. An unreadable file was 2 and is now 4.
> - `validate`: a broken relationship was 2 and is now 6. A workbook that cannot be loaded was 1 and is now 4.
> - `sanitize`, `prune`, `slice`, `docs`: every error was 2. Test for non-zero if you only want to know that it failed, or use 4 (input), 5 (refused), 6 (integrity).
> - `sheet copy`, `dashboard copy`, `library import`, `style export`, `style import`: "some entries were refused, the rest is written" was 2 and is now 7; every other error was 1 and is now 4 or 5.
> - `if [ $? -ne 0 ]` and `set -e` keep working: every failure is still non-zero, and nothing that succeeded changed.
> - The pre-commit hooks still fail for the same files.

A script that tested `== 2` as "broken" or "partial" now sees "usage error" (it would only get there by a typo in the command, so it will mostly see nothing and silently miss the real code). That is the reason the release note is a "Changed" item and not a footnote, and the reason this is a minor version. There is no compatibility switch in the plan; see Open questions.

## 5. Error classes for #186

### What to keep from the issue and what not

Keep: a single base class, and one place to catch it. `PyTbparseError` already exists; the work is to put the remaining sites under it, not to rewrite the classes.

Do not adopt from the issue text:

- **Message suffixes `(code: E001, context: {...})`.** Messages are shown to users in the CLI and in the GUI (`webgui.py` sends `str(e)` to the browser), and tests assert on them. Adding a suffix makes every message longer and breaks every test that matches a message. Exit codes (section 2) are the machine-readable part; a second code system (`E001`) would duplicate them. The issue itself lists "changing error codes in existing code" as out of scope.
- **Constructor arguments `code=` and `context=`.** An exception with required extra arguments breaks `pickle`, and `template apply-folder --workers` runs files in worker processes that send exceptions back. Anything extra must be optional and must not change `str(e)`.
- **`WorkbookError`, `WorkbookNotFoundError`, `InvalidWorkbookError`, `ValidationError` and so on** as a new tree beside the feature classes. They would duplicate `FileNotFoundError` and the feature classes without changing any exit code.
- **A new `exceptions.py` with copies of the feature classes.** The feature classes stay where they are; only the base and the categories move.

### Layout

One new module, `py_tbparse/errors.py` (small, no imports from the rest of the package). `PyTbparseError` moves there; `_xml.py` and `__init__.py` re-export the same object, so `from py_tbparse._xml import PyTbparseError` and `py_tbparse.PyTbparseError` stay valid.

```
PyTbparseError(ValueError)                 # unchanged base, stays a ValueError
  UsageError           -> exit 2           # a bad argument value, found without opening a file
  InputError           -> exit 4           # a file or a name in it cannot be used
  RefusedError         -> exit 5           # declined on purpose, nothing written
    OutputRefusedError(RefusedError, FileExistsError)   # exists, or is an input
  IntegrityError       -> exit 6           # the result has, or would have, broken references
  (feature classes)    SliceError, SanitizeError, PruneError, SheetCopyError, TemplateError,
                       StyleError, LibraryError, ScaffoldError, PackageTooLargeError
```

- The feature classes keep deriving from `PyTbparseError`. They are mapped to 4 when nothing more specific applies (a `TemplateError` for a malformed manifest is bad input). Where a feature class is raised for a refusal or an integrity problem, the site raises a small subclass that has both parents, for example `SliceIntegrityError(SliceError, IntegrityError)` for the `slicer.py:225` site and `class SliceStrictError(SliceError, RefusedError)` for `--strict`. Only the sites that need another code get one; this plan counts them in WP3.
- `OutputRefusedError` derives from `FileExistsError` as well, so every existing `except FileExistsError` (CLI, GUI, tests) keeps working. This is the one wrapping of a built-in that is justified, and it works: a class with parents `ValueError` and `FileExistsError` was checked to be creatable and catchable as both (the standard library does the same with `io.UnsupportedOperation(OSError, ValueError)`). It must be checked again for pickling in WP1.
- The mapping function is `exit_code_for(exc) -> int` in `errors.py`. It checks, in order: `UsageError` 2, `RefusedError` 5, `IntegrityError` 6, `PyTbparseError` (any other) 4, then the built-ins that mean unreadable input or unwritable output (`FileNotFoundError`, `IsADirectoryError`, `PermissionError`, `OSError`, `zipfile.BadZipFile`, `json.JSONDecodeError`, `lxml.etree.XMLSyntaxError`, `pandas.errors.ParserError`) 4, and everything else 3. The `except` tuples in `cli.py` shrink to one handler per run function that calls it. This is the tie to section 2: the table of exit codes is derived from the class, so a new raise site cannot silently get the wrong code.
- A plain `ValueError` that reaches the CLI (a site nobody converted, or one that comes from pandas) is 3, not 4: it is a bug until someone classifies it. That is deliberate and is why WP3 comes before the exit-code WPs.
- Built-ins that are not wrapped: `FileNotFoundError`, `zipfile.BadZipFile`, `json.JSONDecodeError`, `XMLSyntaxError`, `pandas.errors.ParserError`, `OSError`, `PermissionError`. They carry their own message and a file name, callers already catch them, and wrapping them would add a class per library for no new information. Justified exceptions to "no wrapping": `OutputRefusedError` (above), and nothing else in this plan.

### What the plain sites become

38 `ValueError` sites outside `webgui.py` (counted at 1fa6acd) and the 24 `FileExistsError` sites:

| Site(s) | Becomes |
| --- | --- |
| 24 `FileExistsError` ("refusing to overwrite ...") in `cli.py`, `dashboardcopy.py`, `library.py`, `rename.py`, `sanitize.py`, `prune.py`, `scaffold.py`, `sheetcopy.py`, `slicer.py`, `style.py`, `template_batch.py`, `template_drift.py`, `template_update.py`, `templates.py` | `OutputRefusedError` (exit 5). Message text stays. |
| `cli.py:753` ("--output is the template itself; it would be overwritten") | `OutputRefusedError` |
| Unknown table (`batch.py:37`, `diff.py:82`), unknown CI or output format (`ci_formats.py:187`, `findings.py:222`), unknown rule ids and empty `--only` (`findings.py:111,132,135,139`, `cli.py:663`, `template_check.py:67`), `findings.py:63` severity, `precommit.py:32` unknown hook command | `UsageError` (exit 2) |
| `rename.py:91` style, `:236` fuzzy cutoff, `:394` kinds, `:581` exclude type, `:819` output suffix; `templates.py:787` fuzzy cutoff; `template_batch.py:205,207` | `UsageError` |
| `rename.py:471,479` (mapping CSV columns and kinds), `:502` (two renames collide), `:589,595,609` (exclude list problems; these also reach the GUI); `templates.py:873,878` (mapping columns, duplicate mapping); `template_gui.py:140,145` | `InputError` (exit 4) |
| `_xml.py:152` (no `.twb` in `.twbx`), `_xml.py:284` and `parser.py:77` (unsupported file type) | `InputError` |
| `parser.py:276` ("Validation failed", from `validate(error=True)`) | `IntegrityError` (exit 6) |
| `findings.py:77` (rule registered twice), `docgen.py:75,103` (heading level, row width) | stay plain `ValueError`: programmer errors; they are not reachable from user input and a crash (3) is the right answer |

Sites in `webgui.py` (39 `ValueError`): they are validation of a JSON request body, answered as an HTTP 400 with the message. They become `UsageError` (a bad request) or `InputError` (a bad library/palette file the user added), which keeps `except ValueError` and the messages. This has no effect on exit codes and is the last, optional work package.

### Message format rules (new and changed messages only)

Existing messages are not reworded in bulk: tests, docs and users match on them. The rules apply to every message that is added, and to a message that has to be touched anyway:

1. One sentence, no trailing full stop in library exceptions, first word lower case unless it is a name. The CLI adds `error: ` once; the exception text never starts with it.
2. Say what, then which: `what failed: the value or path`. Put the path or the offending value last, in `{x!r}` for values and plain for paths, so a long path does not hide the reason.
3. A refusal says what to do in brackets and names the option once, the way the existing ones do: `refusing to overwrite existing file: out.twb (use --overwrite)`. Library functions name the parameter (`overwrite=True`) only if the CLI does not call them; one message does not carry both.
4. Lists are cut after three entries with the count (`3 of ... : 'a', 'b', 'c'`), as `rename.py:589` already does.
5. No tracebacks, no `repr` of the exception object, no pandas internals; when wrapping text from a lower layer use `from e` so the cause is kept, and put the lower message after a colon only when it is short.
6. No error numbers in text. The exit code is the machine-readable part; a CLI test checks the code, not the message.

### How it ties to the exit codes

The exit code of any CLI error is `exit_code_for(exc)`. `docs/cli.md` gets one table that is generated from the same numbers (`errors.ExitCode`, an `IntEnum`), and `tests/test_exit_codes.py` keeps one case per row. There is no per-command copy of an `except` tuple after WP4 to WP7, so a new command gets the right codes by raising the right class, and a code that nobody classified shows up as 3 (a crash) in tests rather than as a plausible wrong number.

## 6. Work packages

Each is one pull request, in this order. Run the non-browser suite the CI way (`scripts/ci-like-tests.sh`); none of these needs a browser. Nothing is released between packages: WP4 to WP8 change numbers in a documented, per-row-tested way, and the version bump and release notes are a separate owner-run step (WP10). `main` therefore has a mixed scheme between WP4 and WP8; the table in `cli.md` says so at the top until WP8.

**WP1. `errors.py` and the base classes (no behaviour change).**
Add `py_tbparse/errors.py` with `PyTbparseError` (moved), `UsageError`, `InputError`, `RefusedError`, `OutputRefusedError`, `IntegrityError`, `ExitCode`, and `exit_code_for`. Re-export from `_xml.py` and `__init__.py`. Add the module to the table in `AGENTS.md`; update the sentence in `api.md` and the class docstring.
Acceptance: `py_tbparse.PyTbparseError is py_tbparse._xml.PyTbparseError`; every class listed in `api.md` is a subclass; `OutputRefusedError("x")` is caught by `except FileExistsError`, `except ValueError`, `except PyTbparseError` and `except OSError`; all new classes pickle round-trip with `str(e)` unchanged (needed for `--workers`); `exit_code_for` returns the documented number for one instance of each class and for each listed built-in, and 3 for `KeyError`, `RuntimeError` and plain `ValueError`; the whole existing suite passes with no other change.
Risk: multiple inheritance with `OSError` changes `args` handling (`OSError("x")` has `.errno` and `.strerror`); the test must check `str(e)`, `e.args` and pickling. If it misbehaves, fall back to `RefusedError` without `FileExistsError` and convert the `except FileExistsError` sites instead (more work, larger WP2).

**WP2. The 24 `FileExistsError` sites become `OutputRefusedError`.**
Acceptance: a guard test fails if `raise FileExistsError` appears in `py_tbparse/` outside `errors.py`; for each site a case (parametrised, 24 cases or one per module with the existing fixtures) shows the same message as before and that `except FileExistsError` still catches it; the existing suite is unchanged.
Risk: some callers match the message text; the guard compares messages with the current ones verbatim. Small diff, mechanical.

**WP3. The 38 library `ValueError` sites get their classes; feature subclasses for refusal and integrity.**
Does the table in section 5, including `SliceIntegrityError`, `SliceStrictError` and the same for `SheetCopyError` (`--strict`, clash, nothing copyable), `LibraryError` and `StyleError` (clash under fail), `SanitizeError` and `PruneError` (integrity, if they have such sites). First part of the WP is a list of every `raise <FeatureError>` site with its category, put in the PR description; the owner can veto a row there.
Acceptance: a guard test fails on `raise ValueError(` in non-`webgui` modules except an allow-list of the three programmer-error sites; a test per category shows one site raises the expected class and that `except ValueError` still catches it; messages are byte-identical (the existing tests that match messages pass untouched).
Risk: the largest review burden in this plan, because each site is a judgement ("is this usage or bad input?"). Rule used: usage if it could be known without opening a file. Splitting by module in two PRs is allowed if the diff is above about 600 lines.

**WP4. Central exit handling and the crash code (3 everywhere).**
Add `_fail(e)` to `cli.py` using `exit_code_for`; `main()` catches `Exception` and returns 3 with the message `internal error: ...` and the traceback on stderr (today's uncaught exception exits 1). Table commands, `diff`, `batch` and `docs` switch from `return 1` / `return 2` to `_fail`. Rows for these commands in `cli.md` and `test_exit_codes.py` are updated; the document header says the scheme is being rolled out.
Acceptance: a malformed `.twb` given to a table command returns 4 (it was an uncaught traceback, exit 1); an injected failure (monkeypatched function raising `RuntimeError`) returns 3 for a plain table command, for `diff`, for `batch`; `-o` into a missing folder returns 4; argparse errors are 2; `--help` is 0.
Risk: swallowing too much: `Exception` must not catch `KeyboardInterrupt` or `SystemExit`; keep `BrokenPipeError` quiet if the current code does.

**WP5. Checks: `validate`, `audit`, `template check`, `template drift`, `diff-xml`, `style check`.**
`validate` 2 to 6 and 1 to 4; `audit`, `template check`, `template drift`, `diff-xml` unreadable 2 to 4, `diff-xml -o` clash to 5; `style check` unreadable 4. The CI formats (`junit`, `sarif`, `github`) are not changed; their tests assert the code with `--format`.
Acceptance: rows in `test_exit_codes.py` for each case in section 3; `--fail-on never` still returns 0 for a finding and still 3 for a crash; bad `--only`/`--skip` is 2 (not 4); in `tests/test_ci_formats.py`, a `validate` case with a broken relationship returns 6 in all three CI formats.
Risk: `docs/ci.md` is the page users copy from; update it in this WP, not later.

**WP6. Writers that used 2 for everything: `sanitize`, `prune`, `slice`, `rename`, `scaffold`, `docs` leftovers.**
Acceptance: per row in section 3, one case per code: unreadable input 4; output exists and output is input 5; unknown `--keep`, bad extension 2; `slice` unknown dashboard 4, `--strict` 5, `--write` with new integrity problems 6, the same predicted by a dry run 6 (stderr says the same as today); `rename` cutoff 2.
Risk: the `slice` dry-run prediction changes from 2 to 6: it is the case most likely to be tested by an existing CI script, so it has its own line in the release notes.

**WP7. Partial results and clashes: `sheet copy`, `dashboard copy`, `library`, `style export`/`import`, `template` writers, `apply-folder`.**
Acceptance: some sheet/dashboard/palette/entry refused with the rest written returns 7 and the files that should exist exist; a clash under `--on-clash fail` returns 5 and writes nothing (check the output file is absent); `apply-folder` with one bad file returns 7 and `summary.csv` lists it; dry runs stay 0.
Risk: the decision for `library import` dry runs (Open question 5) must be taken before this PR.

**WP8. Pre-commit wrapper and documentation.**
`precommit.py` returns by precedence; `.pre-commit-hooks.yaml` comment, `ci.md`, `cli.md` (one table, the "What the codes mean" section rewritten in the new scheme, the "not one scheme" paragraph removed), `README.md`, `api.md` and `development.md` (the rules for new errors, the message format of section 5) are updated; the per-command pages (`prune.md`, `slice.md`, `sanitize.md`, `sheet-copy.md`, `dashboard-copy.md`, `libraries.md`, `styles.md`, `diff-xml.md`, `audit.md`, `templates.md`) get their exit code lines checked against the table.
Acceptance: unit test of `precommit.main` with mocked `cli_main` returning each pair of codes gives the first of the precedence list; unknown hook command is 2; the doc table equals the `ExitCode` enum (a test reads both); a test greps the docs for the old phrases ("exit code 2 if", "or 2 for any error").
Risk: missing a doc page; the grep test is the guard.

**WP9 (optional). `webgui.py` `ValueError` sites** become `UsageError` / `InputError`. Acceptance: GUI route tests that assert HTTP 400 and the message are unchanged; no `raise ValueError(` left in `py_tbparse/` except the allow-list. Risk: low; no exit code involved. Can be dropped.

**WP10 (owner-run). Release notes and version 0.6.0.** Not part of the plan's PRs: the notes carry the migration text of section 4 under "Changed", and the version bump is done in the release branch. The Python-function defaults that the docs say change in 0.6.0 (`on_clash` becoming `fail`, #128) are a separate item.

Total size: WP1, WP2 and WP9 are mechanical; WP3 is the one that needs review time; WP4 to WP8 are each a handful of commands plus their tests.

### Risks across the plan

- **Silent meaning change of 2.** Covered in the migration note; the scheme avoids reusing a number with a new meaning where it can (`validate` 6, not 1). It cannot avoid it for 2 itself, which is the owner's decision.
- **The GUI and Python callers rely on `ValueError`.** Every new class is a `ValueError`, and `OutputRefusedError` is also a `FileExistsError`; the tests that exist today must pass untouched in WP1 to WP3.
- **`max()` in the pre-commit wrapper** stops being meaningful; replaced in WP8, and the precedence list is documented.
- **Judgement calls at 38 sites** (usage versus bad input). The list is reviewed in WP3 before the exit-code PRs depend on it.
- **Mixed scheme on `main` between WP4 and WP8.** No release in between; the header of the cli.md table says so.
- **Not verified:** the codes of the new scheme exist only in this plan; the counts of raise sites are from `grep` at 1fa6acd and will drift; the claim that a two-parent class with `FileExistsError` works was checked once in the shared venv for creation and `except`, not for pickling or for `OSError` attributes.

## Open questions

For the owner. Each has a default that this plan already assumes.

1. **The numbers.** 0 ok, 1 finding, 2 usage, 3 crash, 4 bad input, 5 refused, 6 integrity, 7 partial. Alternative for the crash: follow the issue (3 unreadable) and move the crash to 70 or so. Default: as listed, 3 stays "crash" because three commands already use it that way.
2. **`validate` with a broken relationship: 6 (default) or 1** (a plain "finding", like `audit`)?
3. **Unknown dashboard, sheet or datasource name: 4 (default) or 2?**
4. **Precedence when several codes apply** (3, 2, 4, 5, 6, 7, 1, 0) and the pre-commit wrapper returning by precedence instead of `max`. OK?
5. **Dry runs.** `library import` as a dry run returns 0 even if entries could not be imported (`--write` would return 7); `style import` as a dry run returns 1 for a clash under `--on-clash fail`. Default in this plan: `style import` dry run clash becomes 5 (as `--write` would be), `library import` dry run stays 0. Should a dry run return the code its real run would, in all commands? (The `slice` dry run already does.)
6. **`apply-folder` where no file was written at all:** 7 (default) or 4?
7. **Compatibility switch** (an environment variable that gives the old codes for one release). Default: no. It doubles the test table and would have to be removed.
8. **No `E001`-style codes or `context` in exceptions** (differs from the text of #186). Default: not adopted; exit codes are the machine-readable part. If the owner wants a `.context` attribute anyway, it can be added as an optional attribute that does not change `str(e)`.
9. **`DashboardCopyError`**: #186 lists it but the code raises `SheetCopyError` for dashboards. Default: do not add a class.
10. **`webgui.py` sites (WP9):** do them in this release, or leave the 39 `ValueError`s alone?
11. **Release grouping.** Should WP1 to WP3 ship earlier in a 0.5.x patch (they change no behaviour) and only WP4 to WP8 wait for 0.6.0? Default: yes, if the owner agrees that a patch may add classes and exports.
