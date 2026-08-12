"""What a video file *should* weigh, and how far past that it actually is.

Raw size is not a verdict. Thirty gigabytes is unremarkable as a three-hour 4K
remux and absurd as a ninety-minute 1080p, so any rule phrased in gigabytes flags
the wrong files in both directions. The comparable quantity is **bytes per hour of
runtime, held against files of the same resolution and codec** — the two things
that legitimately change how much a minute of video costs.

Two properties are load-bearing.

**The baseline is the library's own median, not a constant.** Encoding practice
varies enormously between one collection and another, and a fixed table would
declare a whole tidy library bloated or a whole bloated one fine. Seeds exist only
for buckets with too few files to say anything, and step aside as soon as there is
real evidence.

**Spread is measured with the median absolute deviation, not the standard
deviation.** The outliers are exactly what is being looked for, and a handful of
remuxes drag a mean upward far enough to hide themselves behind it — the
distribution this operates on is guaranteed to be contaminated, which is the
textbook case for a robust estimator.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median

_MS_PER_HOUR = 3_600_000.0

# Bytes per hour that read as ordinary for h264, per rung. Deliberately generous —
# these only apply where the library has too few files of a kind to speak for
# itself, and a seed that is too tight would invent outliers out of nothing.
_SEED_RATE = {
    "480p": 900_000_000,
    "720p": 1_800_000_000,
    "1080p": 3_400_000_000,
    "1440p": 5_600_000_000,
    "2160p": 10_000_000_000,
}

# Cost of a codec relative to h264 at matched quality. Modern codecs buy roughly
# half the bitrate; the older ones cost more. Without this an efficient 1080p h265
# file looks suspiciously small and an mpeg2 rip looks bloated, when both are
# behaving exactly as their format demands.
_CODEC_FACTOR = {
    "h265": 0.55,
    "av1": 0.50,
    "vp9": 0.60,
    "h264": 1.00,
    "vc1": 1.15,
    "mpeg4": 1.30,
    "mpeg2": 2.20,
}
_UNKNOWN_CODEC_FACTOR = 1.00

# Below this a bucket's median is an accident of which few files happen to be in
# it, so the seed is used instead.
MIN_SAMPLES = 8

# MAD scaled by this estimates the standard deviation of a normal distribution;
# it is what makes the multiplier below mean roughly what "sigma" usually means.
_MAD_TO_SIGMA = 1.4826

# How far past typical a file must sit to be called an outlier. Three is
# deliberately conservative: the cost of a false positive here is a person
# re-encoding a file that was fine.
OUTLIER_SIGMAS = 3.0

# A floor on spread, as a fraction of the median. A library encoded from one
# preset can have a MAD near zero, which would make every slightly-larger file a
# three-sigma outlier. Real encodes vary; pretending they don't manufactures
# findings.
_MIN_SPREAD_FRACTION = 0.25


def bytes_per_hour(size: int | None, duration_ms: int | None) -> float | None:
    """The comparable rate, or ``None`` when the file cannot be judged."""
    if not size or size <= 0 or not duration_ms or duration_ms <= 0:
        return None
    return size / (duration_ms / _MS_PER_HOUR)


def codec_factor(codec: str | None) -> float:
    return _CODEC_FACTOR.get((codec or "").lower(), _UNKNOWN_CODEC_FACTOR)


@dataclass(frozen=True)
class Bucket:
    """What files of one resolution and codec typically weigh here."""

    resolution: str
    codec: str
    samples: int
    median_rate: float
    spread: float
    # False when the median is the seed rather than this library's own evidence.
    observed: bool

    @property
    def outlier_rate(self) -> float:
        return self.median_rate + OUTLIER_SIGMAS * self.spread


@dataclass(frozen=True)
class Sample:
    resolution: str | None
    codec: str | None
    size: int | None
    duration_ms: int | None


def _seed_bucket(resolution: str, codec: str) -> Bucket:
    base = _SEED_RATE.get(resolution)
    rate = (base or _SEED_RATE["1080p"]) * codec_factor(codec)
    return Bucket(
        resolution=resolution,
        codec=codec,
        samples=0,
        median_rate=rate,
        spread=rate * _MIN_SPREAD_FRACTION,
        observed=False,
    )


class Baselines:
    """Per-bucket norms for one library."""

    def __init__(self, buckets: dict[tuple[str, str], Bucket]) -> None:
        self._buckets = buckets

    @property
    def buckets(self) -> list[Bucket]:
        return sorted(self._buckets.values(), key=lambda b: (b.resolution, b.codec))

    def bucket(self, resolution: str | None, codec: str | None) -> Bucket | None:
        """The norm to judge a file against, or ``None`` if it cannot be judged.

        A file with no known resolution has no peers, and guessing one would put
        it in a bucket where it is certain to look wrong. Absent evidence yields
        no verdict rather than a bad one.
        """
        if not resolution:
            return None
        key = (resolution, (codec or "unknown").lower())
        found = self._buckets.get(key)
        if found is not None and found.observed:
            return found
        return found or _seed_bucket(resolution, key[1])


def build(samples: Iterable[Sample]) -> Baselines:
    """Measure each bucket's typical rate from the files themselves."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for sample in samples:
        rate = bytes_per_hour(sample.size, sample.duration_ms)
        if rate is None or not sample.resolution:
            continue
        grouped.setdefault((sample.resolution, (sample.codec or "unknown").lower()), []).append(
            rate
        )

    buckets: dict[tuple[str, str], Bucket] = {}
    for (resolution, codec), rates in grouped.items():
        if len(rates) < MIN_SAMPLES:
            buckets[(resolution, codec)] = _seed_bucket(resolution, codec)
            continue
        mid = median(rates)
        mad = median([abs(r - mid) for r in rates]) * _MAD_TO_SIGMA
        buckets[(resolution, codec)] = Bucket(
            resolution=resolution,
            codec=codec,
            samples=len(rates),
            median_rate=mid,
            spread=max(mad, mid * _MIN_SPREAD_FRACTION),
            observed=True,
        )
    return Baselines(buckets)


@dataclass(frozen=True)
class Verdict:
    """How a single file compares with its peers."""

    rate: float
    bucket: Bucket
    # Bytes above what a typical file of this kind would occupy. Zero when the
    # file is at or below typical — this is the disk a re-encode could return, so
    # it must never be optimistic.
    excess: int
    bloated: bool

    @property
    def ratio(self) -> float:
        return self.rate / self.bucket.median_rate if self.bucket.median_rate else 0.0


def judge(
    *,
    size: int | None,
    duration_ms: int | None,
    resolution: str | None,
    codec: str | None,
    baselines: Baselines,
) -> Verdict | None:
    """Compare one file with its peers, or ``None`` when there is no basis to."""
    rate = bytes_per_hour(size, duration_ms)
    bucket = baselines.bucket(resolution, codec)
    if rate is None or bucket is None or not duration_ms:
        return None
    hours = duration_ms / _MS_PER_HOUR
    excess = max(0, int(round((rate - bucket.median_rate) * hours)))
    return Verdict(
        rate=rate,
        bucket=bucket,
        excess=excess,
        bloated=rate > bucket.outlier_rate,
    )


def reencode_saving(
    *,
    size: int | None,
    duration_ms: int | None,
    resolution: str | None,
    from_codec: str | None,
    to_codec: str = "h265",
    baselines: Baselines,
) -> int:
    """Bytes a re-encode would plausibly return. Zero when it would not help.

    Refusing to promise anything for a file already at or below its target is the
    point: re-encoding it spends real quality for no space, and a recommendation
    that cannot tell the difference will eventually make that trade.
    """
    rate = bytes_per_hour(size, duration_ms)
    bucket = baselines.bucket(resolution, from_codec)
    if rate is None or bucket is None or not duration_ms or not size:
        return 0
    if codec_factor(from_codec) <= codec_factor(to_codec):
        return 0
    target_rate = bucket.median_rate / codec_factor(from_codec) * codec_factor(to_codec)
    if rate <= target_rate:
        return 0
    hours = duration_ms / _MS_PER_HOUR
    return max(0, int(round(size - target_rate * hours)))
