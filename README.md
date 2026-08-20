# OceanArray

[![PyPI](https://img.shields.io/pypi/v/oceanarray.svg)](https://pypi.org/project/oceanarray/)
[![Python versions](https://img.shields.io/pypi/pyversions/oceanarray.svg)](https://pypi.org/project/oceanarray/)
[![License: MIT](https://img.shields.io/pypi/l/oceanarray.svg)](https://github.com/ocean-uhh/oceanarray/blob/main/LICENSE)
[![Tests](https://github.com/ocean-uhh/oceanarray/actions/workflows/tests.yml/badge.svg)](https://github.com/ocean-uhh/oceanarray/actions/workflows/tests.yml)
[![Documentation](https://img.shields.io/badge/docs-ocean--uhh.github.io-blue.svg)](https://ocean-uhh.github.io/oceanarray/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21890564.svg)](https://doi.org/10.5281/zenodo.21890564)

Python tools for processing moored oceanographic array observations from raw instrument files to quality-controlled, CF-compliant NetCDF.

**Documentation**: https://ocean-uhh.github.io/oceanarray/

## Installation

```bash
pip install oceanarray
```

This pulls in `seasenselib` (used to read raw instrument files in stage 1) automatically.

Python 3.10–3.12 is supported.

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

oceanarray.process("dsG3_1_2026", raw_dir="/data/raw", proc_dir="/data/proc")
```

See the [API reference](https://ocean-uhh.github.io/oceanarray/oceanarray.html) for the full interface.

## Acknowledgements

Development was assisted by Claude Code (Anthropic) and GitHub Copilot code review.

The data-processing approach draws on methods developed for the RAPID mooring array programme (UK/US funded). `oceanarray` is developed toward the DFG Ocean Array infrastructure project (DFG project number 571027118), from which it takes its name, and was first applied in the AEI–DFG MIXSED project (DFG project number 541914507).

## License

MIT License
