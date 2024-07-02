import argparse
import json

from autoformalization.utils import a_single_job, func_query_and_store

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", type=str, required=True)
    args = parser.parse_args()

    func_query_and_store(args.json_path)
