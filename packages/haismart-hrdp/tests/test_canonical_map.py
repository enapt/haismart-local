"""The map every air conditioner shares, and the one constant that describes the families."""

from haismart_hrdp.canonical_map import CANONICAL, DISPLACEMENTS

# Where the climate attributes begin; everything below is the voice/media section.
_FIRST_CLIMATE_WORD = 20


def test_the_classic_displacement_is_the_span_a_climate_only_model_omits() -> None:
    """-19 is not a fitted constant: it is where the climate block starts, minus one.

    The map opens with a voice/media section -- playback, volume, dialect, recognition, the session
    identifiers -- and the climate attributes begin after it. A model without that hardware starts
    its report at word 1 instead, so every climate attribute lands exactly that many words earlier.

    Note what the constant is *not*: a count of media words. The media attributes stop at word 18
    and word 19 is empty, so counting them gives 18. What -19 measures is the whole omitted span up
    to the climate boundary, which is why the assertion below is written against that boundary and
    not against the size of the section.
    """
    media = {n: f for n, f in CANONICAL.items() if f.word < _FIRST_CLIMATE_WORD}
    climate_start = min(f.word for n, f in CANONICAL.items() if n not in media)

    assert climate_start == _FIRST_CLIMATE_WORD
    assert len(media) == 26                       # attributes, not words -- they share words
    # a climate-only model puts climate_start at word 1, so it reads (climate_start - 1) earlier
    assert -(climate_start - 1) in DISPLACEMENTS
    assert -(climate_start - 1) == -19


def test_the_media_block_is_contiguous_and_holds_no_climate_attribute() -> None:
    """Nothing climate-related hides below the boundary, which is what makes the shift a clean cut.

    If a single climate attribute sat inside the media block, a model omitting that block would have
    to move it somewhere rather than simply start lower, and one whole-word displacement could not
    describe the family. It does, so the cut is clean.
    """
    media = sorted({f.word for f in CANONICAL.values() if f.word < _FIRST_CLIMATE_WORD})

    assert min(media) == 1
    assert max(media) == _FIRST_CLIMATE_WORD - 2   # word 19 carries nothing
    assert 6 not in media                          # nor does word 6, inside the run
    for name in ("targetTemperature", "onOffStatus", "operationMode", "indoorTemperature"):
        assert CANONICAL[name].word >= _FIRST_CLIMATE_WORD
