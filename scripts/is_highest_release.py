"""Print "true" if VERSION is at least as high as every release tag read from stdin, else "false".

Used by .github/workflows/docker-publish.yml to decide whether the image gets the `latest` tag, so that
publishing a hotfix such as 0.5.2.post1 after 0.5.4 does not move `latest` back. Tags look like v0.5.4 or
v0.5.2.post1; anything else (a tag that is not X.Y.Z[.postN]) is ignored.

    gh release list --json tagName,isPrerelease,isDraft --jq '.[]|select(.isPrerelease|not)|select(.isDraft|not)|.tagName' \
        | python3 scripts/is_highest_release.py 0.5.4
"""
import re
import sys

_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)(?:\.post(\d+))?$")


def version_key(text):
    """Sort key for X.Y.Z[.postN]; None when the text is not in that form."""
    m = _VERSION.match(text.strip())
    if not m:
        return None
    nums = [int(p) for p in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    return (tuple(nums), int(m.group(2) or 0))


def is_highest(version, tags):
    mine = version_key(version)
    if mine is None:
        raise ValueError(f"not a release version: {version!r}")
    return all(mine >= k for k in map(version_key, tags) if k is not None)


if __name__ == "__main__":
    print("true" if is_highest(sys.argv[1], sys.stdin.read().split()) else "false")
