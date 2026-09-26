#!/usr/bin/env python3
"""Download and extract the latest South East Queensland Translink GTFS feed."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


SOURCE_URL = "https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "SEQ_GTFS"
CORE_FILES = {"agency.txt", "routes.txt", "stops.txt", "trips.txt", "stop_times.txt"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the latest Translink SEQ GTFS feed."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"destination directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--url",
        default=SOURCE_URL,
        help="GTFS ZIP URL; primarily useful for testing",
    )
    return parser.parse_args()


def download(url: str, destination: Path) -> tuple[str, int]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "UQGEMs-GeoRabble GTFS downloader"},
    )
    digest = hashlib.sha256()
    size = 0

    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open(
            "wb"
        ) as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except urllib.error.URLError as error:
        raise RuntimeError(f"could not download {url}: {error}") from error

    return digest.hexdigest(), size


def select_feed_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Find the directory in the ZIP that contains the core GTFS text files."""
    groups: dict[PurePosixPath, dict[str, zipfile.ZipInfo]] = {}

    for entry in archive.infolist():
        if entry.is_dir():
            continue
        path = PurePosixPath(entry.filename)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".txt":
            continue
        group = groups.setdefault(path.parent, {})
        if path.name in group:
            raise RuntimeError(f"duplicate file in GTFS archive: {path.name}")
        group[path.name] = entry

    candidates = [entries for entries in groups.values() if CORE_FILES <= entries.keys()]
    if len(candidates) != 1:
        raise RuntimeError(
            "downloaded ZIP does not contain exactly one recognisable GTFS feed"
        )

    entries = candidates[0]
    if not ({"calendar.txt", "calendar_dates.txt"} & entries.keys()):
        raise RuntimeError("GTFS feed has neither calendar.txt nor calendar_dates.txt")
    return list(entries.values())


def extract_feed(archive_path: Path, staging: Path) -> list[Path]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = select_feed_entries(archive)
            extracted = []
            for entry in entries:
                destination = staging / PurePosixPath(entry.filename).name
                with archive.open(entry) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                extracted.append(destination)
            return extracted
    except zipfile.BadZipFile as error:
        raise RuntimeError("downloaded file is not a valid ZIP archive") from error


def feed_dates(feed_info_path: Path) -> dict[str, str]:
    if not feed_info_path.exists():
        return {}
    with feed_info_path.open(newline="", encoding="utf-8-sig") as source:
        row = next(csv.DictReader(source), None)
    if not row:
        return {}
    return {
        key: row[key]
        for key in ("feed_start_date", "feed_end_date")
        if row.get(key)
    }


def install_feed(
    extracted: list[Path], output_directory: Path, metadata: dict[str, object]
) -> None:
    # Replace only GTFS text files. Documentation and unrelated files are preserved.
    for existing in output_directory.glob("*.txt"):
        existing.unlink()
    for source in extracted:
        source.replace(output_directory / source.name)

    metadata.update(feed_dates(output_directory / "feed_info.txt"))
    metadata_path = output_directory / "download_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_directory = args.output.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(
            prefix=".seq-gtfs-download-", dir=output_directory
        ) as temporary_directory:
            temporary = Path(temporary_directory)
            archive_path = temporary / "SEQ_GTFS.zip"
            staging = temporary / "extracted"
            staging.mkdir()

            print(f"Downloading {args.url}")
            archive_sha256, archive_size = download(args.url, archive_path)
            extracted = extract_feed(archive_path, staging)
            metadata: dict[str, object] = {
                "source_url": args.url,
                "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                "archive_sha256": archive_sha256,
                "archive_size_bytes": archive_size,
            }
            install_feed(extracted, output_directory, metadata)
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(
        f"Installed {len(extracted)} GTFS files in {output_directory} "
        f"({archive_size / (1024 * 1024):.1f} MiB downloaded)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
