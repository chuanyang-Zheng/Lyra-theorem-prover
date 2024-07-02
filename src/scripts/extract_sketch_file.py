import os
from autoformalization.utils import ROOTDIR
import json
from tqdm import tqdm

def list_file_name(directory):
    onlyfiles = [f[:-4] for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    return onlyfiles
def get_test_file():
    test_all = list_file_name(os.path.join(ROOTDIR,"data/isabelle/test"))
    test_all.extend(["imosl_2007_algebra_p6"])

    return test_all

test_list=get_test_file()
valid_list=list_file_name("data/isabelle/valid")

data_name = "chuanyang_sketch_all_test_gpt35turbo"
dump_dir = f"dump/{data_name}"
output_dir = os.path.join(ROOTDIR, f"isabelle_output/miniF2F/output_{data_name}")
print(output_dir)
# if not os.path.exists(output_dir):
#     os.makedirs(output_dir)
with open(dump_dir+".json", encoding='utf-8') as f:
    sketch_data = json.load(f)

with open(os.path.join(ROOTDIR, "data/minif2f.json"), encoding='utf-8') as f:
    minif2f_data = json.load(f)

for problem_name, info in tqdm(sketch_data.items()):
    # print(info)
    if "_genproof" in problem_name:
        raw_name = problem_name[:problem_name.find("_genproof")]
    else:
        raw_name = problem_name
    header = minif2f_data[raw_name]['isa_header']
    for gen_id, content in enumerate(info):
        # print(gen_id)
        # print(content)
        statement = content['problem']['formal_statement']
        generated = content['generation']

        if problem_name in test_list:
            save_path=os.path.join(output_dir,"test", f"{problem_name}_sketch{gen_id}.thy")
        elif problem_name in valid_list:
            save_path = os.path.join(output_dir,"valid", f"{problem_name}_sketch{gen_id}.thy")
        else:
            print(problem_name)
            break

        if not os.path.exists(os.path.dirname(save_path)):
            os.makedirs(os.path.dirname(save_path))

        with open(save_path, "w", encoding='utf-8') as f:
            f.write(header + "(*statement begin*)\n" + statement + "(*statement end*)\n" + generated + "\nend\n")
        # break
