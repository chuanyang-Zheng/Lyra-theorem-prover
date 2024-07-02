import os
from src.isa_auto.utils_auto import ROOTDIR
import json
from tqdm import tqdm
data_dir = os.path.join(ROOTDIR, "data")
output_dir = os.path.join(data_dir, "isabelle/miniF2F/sketch_dsp_first")
if not os.path.exists(output_dir):
    os.makedirs(output_dir)
with open(os.path.join(data_dir, "isabelle/merge_first_2.json"), encoding='utf-8') as f:
    sketch_data = json.load(f)

with open(os.path.join(data_dir, "minif2f.json"), encoding='utf-8') as f:
    minif2f_data = json.load(f)

for problem_name, info in tqdm(sketch_data.items()):
    statement = info['formal_statement']
    generated = info['generation']
    header = minif2f_data[problem_name]['isa_header']
    for gen_id, content in enumerate(generated):
        with open(os.path.join(output_dir, f"{problem_name}_sketch{gen_id}.thy"), "w") as f:
            f.write(header + "(*statement begin*)\n" + statement + "(*statement end*)\n" + content + "\nend\n")
