from pathlib import Path

import pytest
from lxml import etree

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def wenjie_xml():
    return etree.parse(str(FIXTURES / "test_for_wenjie.twb"))


@pytest.fixture
def wenjie_path():
    return str(FIXTURES / "test_for_wenjie.twb")


@pytest.fixture
def zip_twbx_path():
    return str(FIXTURES / "test_for_zip.twbx")


def xml_from_string(s: str):
    return etree.fromstring(s.encode("utf-8"))
