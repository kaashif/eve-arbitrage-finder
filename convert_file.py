#!/usr/bin/env python3.11
from io import StringIO

import pandas as pd
import bz2
import sys

csv_bz2_filename = sys.argv[1]
parquet_filename = csv_bz2_filename.replace(".csv.bz2", ".parquet")

with bz2.open(csv_bz2_filename, mode="r") as data_csv:
    contents = StringIO(bytes.decode(data_csv.read(), "utf-8"))

df = pd.read_csv(contents)
df.to_parquet(parquet_filename, compression="gzip")