# Use the checks in CI

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

`validate`, `template check` and `audit` can write their findings as JUnit XML, SARIF 2.1.0 or GitHub workflow commands, so a pipeline can show them as test results, code-scanning alerts or pull-request annotations. The rules and the exit codes are the same as for the table output. Nothing here was run against Tableau, GitHub code scanning or a particular CI product beyond the tests in this repository, which parse the output with the Python standard library and check the SARIF structure by hand.

```bash
py-tbparse audit sales.twb --format github                 # ::error file=sales.twb,title=A003::...
py-tbparse audit sales.twb --format junit -o audit.xml
py-tbparse audit sales.twb --format sarif -o audit.sarif --fail-on never
py-tbparse template check sales.template.twbx --format sarif -o check.sarif
py-tbparse sales.twb validate --format junit -o validate.xml
```

`--format` takes `table`, `csv`, `json`, `junit`, `sarif` or `github` for `audit` and `template check`. For `validate` the plain formats are the ones it always had (`table`, `json`) plus the three CI formats; the other tables refuse a CI format.

## Exit codes

They do not depend on the format and did not change.

| Command | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| `audit`, `template check`, `template drift` | no finding at `--fail-on` (default `error`) | a finding at or above `--fail-on` | file cannot be read, or a bad option | a rule crashed (the traceback goes to stderr) |
| `validate` | relationships are fine | the workbook cannot be loaded | a relationship refers to a table or field the workbook lacks | (not used) |

The other commands (`sanitize`, `prune`, `slice`, `sheet copy`, `library import` and the rest) use 1 and 2 in their own ways: the full table is in [cli.md](cli.md#exit-codes).

So a pipeline step that must not fail on warnings can write a report with `--fail-on never` and still see exit 3 if py-tbparse itself failed.

## Rule ids

Rule ids are stable and never reused, so they are safe in configs and in suppression lists: `A001` to `A011` for `audit`, `T001` to `T010` for `template check`, `D001` to `D011` for `template drift` (the location of a finding is the folder or glob; the file is in the object), and for `validate`:

| Id | Severity | What it finds |
| --- | --- | --- |
| V001 | error | A relationship refers to a table the workbook does not have. |
| V002 | error | A relationship refers to a field the workbook does not have. |

## JUnit

`<testsuites><testsuite><testcase classname="A003" name="[Calc]" file="sales.twb">`, one test case per finding. An `error` finding is a `<failure type="A003" message="...">`. A `warning` or `info` finding is `<skipped message="warning: ...">`, so the report lists it without failing. A crashed rule is an `<error>`. With no findings the suite has one passing test case named `no findings`.

## SARIF

SARIF 2.1.0: one run, `tool.driver.rules` holds every rule of the command (id, title, default level, fix text), and each result has `ruleId`, `ruleIndex`, a `level` (`error`, `warning`, and `note` for `info`), the message and one location, the workbook or template file as you gave it on the command line (forward slashes, so a relative path stays relative to the repository), at line 1. The object the finding is about and the suggested fix are in `properties`. A finding is about a file, not a line, because the commands read XML structure, not source lines.

## GitHub

One workflow command per finding: `::error file=sales.twb,title=A003::[Calc]: refers to [Gone] (fix: ...)`. `warning` is `::warning`, `info` is `::notice`. The message escapes `%`, CR and LF, and the `file` and `title` values also escape `:` and `,`, as the runner expects.

## Sample workflow

[`docs/examples/py-tbparse-ci.yml`](examples/py-tbparse-ci.yml) is a workflow to copy into your own repository (it is deliberately not in this repository's `.github/workflows`). It annotates a pull request with `--format github` and stores JUnit and SARIF reports as an artifact. Uploading SARIF to code scanning needs `github/codeql-action/upload-sarif` and the `security-events: write` permission; it is not part of the sample and was not tried.

## pre-commit

The repository has a `.pre-commit-hooks.yaml` with three hooks:

```yaml
repos:
  - repo: https://github.com/DDSNA/py-tbparse
    rev: v0.5.2            # a release tag that contains the hook file
    hooks:
      - id: py-tbparse-audit
        args: [--fail-on, warning]
      - id: py-tbparse-validate
      - id: py-tbparse-template-check      # only files named *.template.twbx
```

pre-commit gives a hook many files at once; `python -m py_tbparse.precommit` runs the command for each file and returns the worst exit code. Arguments that end in `.twb` or `.twbx` are files, the rest go to the command. The hook file itself was parsed as YAML but not run by pre-commit here.
