# Legacy demo notebooks

These notebooks are kept for reference but are **not** part of the current workflow. Two groups:

**Old RODB/RAPID-format notebooks** (deprecated functionality):
- `demo_instrument_rdb.ipynb` - RODB instrument processing
- `demo_mooring_rdb.ipynb` - RODB mooring processing
- `demo_batch_instrument.ipynb` - batch processing and QC analysis

**Notebooks that use the pre-subpackage API** (moved here because they no longer import against the
current package):
- `demo_stage1.ipynb`, `demo_stage2.ipynb`, `demo_instrument.ipynb` - the removed staged API
  (`oceanarray.stage1.MooringProcessor`, `process_multiple_moorings_stage2`); superseded by
  `../demo_mooring.ipynb`, which runs the same raw-to-grid pipeline via `process()`.
- `demo_check_clock.ipynb`, `demo_clock_offset.ipynb` - break only on moved-module imports
  (`find_deployment`, `clock_offset` now live under the subpackages); candidates to fix and move
  back out of legacy.

For current usage, see the notebooks in the parent directory:
- `../demo_mooring.ipynb` - raw files to stage 1/2/3, stack, grid via `oceanarray.processors.process`
- `../demo_climatology.ipynb` - RAPID climatological-gradient gridding
