from autoformalization.utils import ROOTDIR
import os
import json
dump_dir = os.path.join(ROOTDIR, "dump/chuanyang_sketch_all_test_gpt35turbo")
file_list = os.listdir(dump_dir)

def get_problem_id(_file):
    return "_".join(_file.split("_")[:-1])

merge_generation = {}
for _file in file_list:
    if not _file.endswith(".json") or not _file.startswith("generation"):
        continue
    with open(os.path.join(dump_dir, _file)) as f:
        data = json.load(f)
    for problem_id, generated in data.items():
        if problem_id not in merge_generation:
            merge_generation[problem_id] = generated
        else:
            merge_generation[problem_id].extend(generated)
print(len(merge_generation))
with open(os.path.join(ROOTDIR, "dump/chuanyang_sketch_all_test_gpt35turbo.json"), "w") as f:
    json.dump(merge_generation, f, indent=2)
