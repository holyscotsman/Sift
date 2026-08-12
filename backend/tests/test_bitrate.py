"""Bitrate baselines — the arithmetic every size verdict rests on.

The claim under test is that size is only meaningful once runtime, resolution and
codec are held constant. Each control below breaks one of those three and shows
the wrong file getting flagged.
"""

from __future__ import annotations

from sift.analysis import bitrate

GB = 1_000_000_000
HOUR_MS = 3_600_000


def _samples(resolution: str, codec: str, rates_gb_per_hour: list[float]) -> list[bitrate.Sample]:
    """Files of one kind, two hours each, at the given rates."""
    return [
        bitrate.Sample(
            resolution=resolution,
            codec=codec,
            size=int(rate * 2 * GB),
            duration_ms=2 * HOUR_MS,
        )
        for rate in rates_gb_per_hour
    ]


def _ordinary_library() -> bitrate.Baselines:
    return bitrate.build(
        _samples("1080p", "h264", [3.0, 3.1, 3.2, 2.9, 3.3, 3.0, 3.1, 2.8, 3.2, 3.0])
        + _samples("2160p", "h264", [9.0, 9.5, 10.0, 9.2, 9.8, 9.1, 9.6, 10.2, 9.4, 9.9])
    )


def test_rate_is_per_hour_not_per_file():
    assert bitrate.bytes_per_hour(6 * GB, 2 * HOUR_MS) == 3 * GB
    assert bitrate.bytes_per_hour(3 * GB, HOUR_MS) == 3 * GB


def test_a_file_with_no_duration_cannot_be_rated():
    """NEGATIVE CONTROL: a zero duration would divide into an enormous rate and
    condemn every file whose runtime failed to parse."""
    assert bitrate.bytes_per_hour(6 * GB, None) is None
    assert bitrate.bytes_per_hour(6 * GB, 0) is None
    assert bitrate.bytes_per_hour(None, HOUR_MS) is None


# ------------------------------------------------------------------ the baseline


def test_the_baseline_is_the_librarys_own_median():
    base = _ordinary_library()
    bucket = base.bucket("1080p", "h264")
    assert bucket is not None and bucket.observed
    assert 2.9 * GB < bucket.median_rate < 3.2 * GB


def test_a_thin_bucket_falls_back_to_the_seed():
    """NEGATIVE CONTROL: three files cannot establish a norm. Trusting them would
    let one odd rip define what 'typical' means for its whole rung."""
    base = bitrate.build(_samples("1080p", "h264", [12.0, 12.5, 13.0]))
    bucket = base.bucket("1080p", "h264")
    assert bucket is not None
    assert not bucket.observed
    assert bucket.median_rate < 12 * GB  # the seed, not those three remuxes


def test_a_handful_of_remuxes_cannot_hide_behind_the_average():
    """The reason for median and MAD rather than mean and standard deviation: a
    contaminated distribution is exactly what this operates on."""
    rates = [3.0] * 20 + [30.0] * 4
    base = bitrate.build(_samples("1080p", "h264", rates))
    bucket = base.bucket("1080p", "h264")
    assert bucket is not None

    mean_rate = sum(rates) / len(rates) * GB
    assert bucket.median_rate < mean_rate  # ~3 GB/h, not the ~7.5 GB/h mean

    verdict = bitrate.judge(
        size=int(30 * 2 * GB), duration_ms=2 * HOUR_MS,
        resolution="1080p", codec="h264", baselines=base,
    )
    assert verdict is not None and verdict.bloated


# --------------------------------------------------------------------- verdicts


def test_a_bloated_1080p_film_is_flagged():
    base = _ordinary_library()
    verdict = bitrate.judge(
        size=30 * GB, duration_ms=int(1.5 * HOUR_MS),
        resolution="1080p", codec="h264", baselines=base,
    )
    assert verdict is not None
    assert verdict.bloated
    assert verdict.excess > 20 * GB


def test_the_same_thirty_gigabytes_as_a_long_4k_film_is_not_flagged():
    """NEGATIVE CONTROL and the whole point. Drop resolution from the bucketing
    and this file is judged against 1080p peers, which condemns it."""
    base = _ordinary_library()
    verdict = bitrate.judge(
        size=30 * GB, duration_ms=3 * HOUR_MS,
        resolution="2160p", codec="h264", baselines=base,
    )
    assert verdict is not None
    assert not verdict.bloated
    # Fractionally above its peers, not the 20 GB of waste the identical byte
    # count represents when it is a ninety-minute 1080p.
    assert verdict.excess < 2 * GB


def test_an_efficient_codec_is_not_punished_for_being_small():
    """An h265 file at half the h264 rate is behaving correctly, not suspiciously."""
    base = bitrate.build(
        _samples("1080p", "h264", [3.0] * 10) + _samples("1080p", "h265", [1.7] * 10)
    )
    verdict = bitrate.judge(
        size=int(1.7 * 2 * GB), duration_ms=2 * HOUR_MS,
        resolution="1080p", codec="h265", baselines=base,
    )
    assert verdict is not None
    assert not verdict.bloated
    assert verdict.excess == 0


def test_a_file_of_unknown_resolution_gets_no_verdict():
    """NEGATIVE CONTROL: it has no peers, and assigning it a rung guarantees a
    wrong answer. Insufficient evidence must stay insufficient."""
    base = _ordinary_library()
    assert bitrate.judge(
        size=30 * GB, duration_ms=HOUR_MS, resolution=None, codec="h264", baselines=base
    ) is None


def test_excess_is_never_negative():
    """Excess is disk you would get back. A small file offering negative bytes
    would quietly subtract from the total the planner adds up."""
    base = _ordinary_library()
    verdict = bitrate.judge(
        size=1 * GB, duration_ms=2 * HOUR_MS,
        resolution="1080p", codec="h264", baselines=base,
    )
    assert verdict is not None
    assert verdict.excess == 0


# ------------------------------------------------------------------- re-encoding


def test_a_bloated_h264_film_has_something_to_gain():
    base = _ordinary_library()
    saving = bitrate.reencode_saving(
        size=30 * GB, duration_ms=int(1.5 * HOUR_MS),
        resolution="1080p", from_codec="h264", baselines=base,
    )
    assert saving > 20 * GB


def test_a_file_already_at_target_efficiency_is_offered_nothing():
    """NEGATIVE CONTROL: promising a saving here spends real quality for no space.
    A recommendation engine that cannot tell will eventually make that trade."""
    base = _ordinary_library()
    assert bitrate.reencode_saving(
        size=int(1.6 * 2 * GB), duration_ms=2 * HOUR_MS,
        resolution="1080p", from_codec="h265", baselines=base,
    ) == 0
    assert bitrate.reencode_saving(
        size=int(1.0 * 2 * GB), duration_ms=2 * HOUR_MS,
        resolution="1080p", from_codec="h264", baselines=base,
    ) == 0


def test_converting_to_a_codec_no_better_than_the_source_gains_nothing():
    """NEGATIVE CONTROL: even an oversized file has nothing to gain from a format
    that is no more efficient than the one it is already in. The size is real, but
    a codec conversion is not the thing that fixes it — and offering one spends a
    generation of quality to arrive back where it started."""
    base = bitrate.build(_samples("1080p", "h265", [1.7] * 10))
    oversized = int(8.0 * 2 * GB)  # far above the h265 median for this library

    assert bitrate.reencode_saving(
        size=oversized, duration_ms=2 * HOUR_MS,
        resolution="1080p", from_codec="h265", to_codec="h265", baselines=base,
    ) == 0
    assert bitrate.reencode_saving(
        size=oversized, duration_ms=2 * HOUR_MS,
        resolution="1080p", from_codec="av1", to_codec="h265", baselines=base,
    ) == 0

    # It is still recognised as oversized — the size problem is real, only the
    # codec conversion is the wrong remedy.
    verdict = bitrate.judge(
        size=oversized, duration_ms=2 * HOUR_MS,
        resolution="1080p", codec="h265", baselines=base,
    )
    assert verdict is not None and verdict.bloated
