# OceanArray

Python tools for processing moored oceanographic array observations from raw instrument files to quality-controlled, CF-compliant NetCDF.

**Documentation**: https://ocean-uhh.github.io/oceanarray/

## Installation

```bash
pip install oceanarray
```

`seasenselib` is required for reading raw instrument files (available on PyPI but needs `--no-deps`):

```bash
pip install pyrsktools pycnv
pip install seasenselib --no-deps
```

Python 3.9–3.12 is supported.

## Quick start

Create a skeleton YAML, fill in the deployment metadata, then process:

```bash
oceanarray init dsG3_1_2026 --proc-dir /data/proc
# edit /data/proc/dsG3_1_2026/dsG3_1_2026.mooring.yaml
oceanarray validate /data/proc/dsG3_1_2026/dsG3_1_2026.mooring.yaml
oceanarray process dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --stage 1 2 3 stack grid
oceanarray report  dsG3_1_2026 --raw-dir /data/raw --proc-dir /data/proc --all
```

See the [documentation](https://ocean-uhh.github.io/oceanarray/) for the recommended first-processing workflow, YAML reference, and CLI reference.

## Python API

```python
import oceanarray

oceanarray.process('dsG3_1_2026', raw_dir='/data/raw', proc_dir='/data/proc')
```

See the [API reference](https://ocean-uhh.github.io/oceanarray/oceanarray.html) for the full interface.

## License

MIT License
