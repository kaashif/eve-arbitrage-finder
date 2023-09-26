#!/usr/bin/env python3.11
from io import StringIO
from datetime import datetime

import pandas as pd
import bz2
import sys

csv_bz2_filenames = sys.argv[1:]
num_files = len(csv_bz2_filenames)

print(f"{num_files=}")

file_num = 0

for csv_bz2_filename in csv_bz2_filenames:
    start = datetime.now()
    print(f"{file_num=}: ", end="")
    file_num += 1

    parquet_filename = csv_bz2_filename.replace(".csv.bz2", ".parquet")

    with bz2.open(csv_bz2_filename, mode="r") as data_csv:
        contents = StringIO(bytes.decode(data_csv.read(), "utf-8"))

    df = pd.read_csv(contents)
    df.to_parquet(parquet_filename, compression="gzip")
    end = datetime.now()
    time_taken = end-start

    time_left = (num_files - file_num) * time_taken
    print(time_left)
