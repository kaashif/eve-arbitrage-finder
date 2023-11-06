#!/usr/bin/env python3.11
from io import StringIO
from datetime import datetime
from fastavro import writer, parse_schema

import pandas as pd
import bz2
import sys

csv_bz2_filenames = sys.argv[1:]
num_files = len(csv_bz2_filenames)

print(f"{num_files=}")

file_num = 0

def dtype_to_avro_type(dtype):
    match dtype.name:
        case "int64":
            return "long"
        case "bool":
            return "boolean"
        case "object":
            return "string"
        case "float64":
            return "double"
    raise Exception(f"unknown type {dtype}")

for csv_bz2_filename in csv_bz2_filenames:
    start = datetime.now()
    print(f"{file_num=}: ", end="")
    file_num += 1

    avro_filename = csv_bz2_filename.replace(".csv.bz2", ".avro")

    with bz2.open(csv_bz2_filename, mode="r") as data_csv:
        contents = StringIO(bytes.decode(data_csv.read(), "utf-8"))

    df = pd.read_csv(contents)
    records = df.to_dict("records")

    schema = {
        "doc": "evetrades",
        "name": "evetrades",
        "namespace": "evetrades",
        "type": "record",
        "fields": [
            {"name": name, "type": dtype_to_avro_type(dtype)}
            for name,dtype in df.dtypes.items()
        ],
    }

    parsed_schema = parse_schema(schema)

    with open(avro_filename, "wb") as out:
        writer(out, parsed_schema, records, codec="snappy")

    end = datetime.now()
    time_taken = end - start

    time_left = (num_files - file_num) * time_taken
    print(time_left)
