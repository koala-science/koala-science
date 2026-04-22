import pytest

from app.schemas.auth import OPENREVIEW_ID_PATTERN


@pytest.mark.parametrize(
    "openreview_id",
    [
        "~First_Last1",
        "~Jane_Smith42",
        "~Eugenio_Herrera-Berg1",
        "~Tomás_Vergara_Browne1",
        "~François_Léger1",
        "~Søren_Kierkegaard1",
        "~周_树人1",
    ],
)
def test_valid_ids(openreview_id: str) -> None:
    assert OPENREVIEW_ID_PATTERN.match(openreview_id) is not None


@pytest.mark.parametrize(
    "openreview_id",
    [
        "First_Last1",
        "~First_Last",
        "~1First1",
        "~_First1",
        "~-First1",
        "~First Last1",
        "",
    ],
)
def test_invalid_ids(openreview_id: str) -> None:
    assert OPENREVIEW_ID_PATTERN.match(openreview_id) is None
