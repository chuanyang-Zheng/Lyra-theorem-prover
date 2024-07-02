from autoformalization.utils import ROOTDIR
import os
import json

prompt_dir = os.path.join(ROOTDIR, "data/paper_prompt_examples")
prompt_list = os.listdir(prompt_dir)
with open("dsp_prompts.txt", "w") as out_f:
    for prompt_file in prompt_list:
        with open(os.path.join(prompt_dir, prompt_file)) as f:
            prompt_data = json.load(f)
        tag = prompt_data['tag']
        prompt = prompt_data['prompt']
        category = prompt_data['category']
        out_f.write(tag+" "+category + "\n")
        out_f.write(prompt+"\n\n")

