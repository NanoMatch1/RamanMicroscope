"""Where this exploration's scripts read the 2026-11-18 data and write their outputs.

The data are not in git. Set STAGE1_EDGE_DATA_DIRECTORY to the folder holding s1edge/, s1step/,
s1ref/ and the run logs; the default is scratch/2026-11-18 under the repository root. Outputs go
to output/ next to the scripts (not in git).
"""
import os

DATA_DIRECTORY = os.environ.get('STAGE1_EDGE_DATA_DIRECTORY', 'scratch/2026-11-18')
OUTPUT_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
