# Translink South East Queensland GTFS data

The GTFS data files in this directory are downloaded inputs and are deliberately
excluded from Git. To download or refresh the latest feed, run this command from
the repository root:

```bash
python3 scripts/download_seq_gtfs.py
```

The downloader retrieves Translink's current `SEQ_GTFS.zip`, validates its basic
GTFS structure, and replaces the local `.txt` files only after the new archive
has downloaded and validated successfully. It also writes
`download_metadata.json` with the source URL, download time, archive SHA-256, and
feed validity dates.

## Data source and licence

- Publisher: Department of Transport and Main Roads, Translink Division
- Source: <https://gtfsrt.api.translink.com.au/GTFS/SEQ_GTFS.zip>
- Information: <https://translink.com.au/about-translink/open-data>
- Licence: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)

Because the source URL always serves the current schedule, downloads made on
different dates may contain different feed versions. Keep the generated
`download_metadata.json` with analysis outputs when an exact input version must
be auditable.
