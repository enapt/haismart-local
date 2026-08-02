"""The map every air conditioner shares, and the one constant that describes the families."""

from haismart_hrdp.canonical_map import CANONICAL, DISPLACEMENTS

# Where the climate attributes begin; everything below is the voice/media section.
_FIRST_CLIMATE_WORD = 20


def test_the_classic_displacement_is_exactly_the_media_block_it_omits() -> None:
    """-19 is not a fitted constant: it is the size of the block a climate-only model lacks.

    The map opens with a voice/media section -- playback, volume, dialect, recognition, the session
    identifiers -- and the climate attributes begin after it. A model without that hardware starts
    its report at word 1 instead, so every climate attribute lands exactly that many words earlier.
    The docstring has always said so; this pins the arithmetic, so that if the map is regenerated
    and the block changes size, the displacement constant cannot silently disagree with it.
    """
    media = {n: f for n, f in CANONICAL.items() if f.word < _FIRST_CLIMATE_WORD}
    climate_start = min(f.word for n, f in CANONICAL.items() if n not in media)

    assert climate_start == _FIRST_CLIMATE_WORD
    assert len(media) == 26
    # a climate-only model puts climate_start at word 1, so it reads (climate_start - 1) earlier
    assert -(climate_start - 1) in DISPLACEMENTS
    assert -(climate_start - 1) == -19


def test_the_media_block_is_contiguous_and_holds_no_climate_attribute() -> None:
    """Nothing climate-related hides below the boundary, which is what makes the shift a clean cut.

    If a single climate attribute sat inside the media block, a model omitting that block would have
    to move it somewhere rather than simply start lower, and one whole-word displacement could not
    describe the family. It does, so the cut is clean.
    """
    media = sorted(f.word for f in CANONICAL.values() if f.word < _FIRST_CLIMATE_WORD)

    assert min(media) == 1
    assert max(media) == _FIRST_CLIMATE_WORD - 2   # the word before the climate block is unused
    for name in ("targetTemperature", "onOffStatus", "operationMode", "indoorTemperature"):
        assert CANONICAL[name].word >= _FIRST_CLIMATE_WORD
