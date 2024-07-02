import copy
import pickle

import openai
from openai import OpenAI
import time
import os
import json
import socket
import random
import subprocess
import re
import gc
import fcntl
import requests







def lock(f):
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
def un_lock(f):
    fcntl.flock(f, fcntl.LOCK_UN)






ROOTDIR = os.path.abspath(os.path.join(__file__, os.path.pardir, os.path.pardir))
from src.isa_auto.proof_completor import ProofCompletorISA

save_para_json_name= {"tag",
                     "prompt_sample",
                     "generation_params",
                     "hashed_id",
                     "prompt_examples",
                     "problem",
                     "dump_path",
                     "SLURM_ARRAY_TASK_ID",
                    }

def get_problem_names(split='test'):
    directory = f"draft_data/isabelle/{split}"
    problem_names = [f.split(".")[0] for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

    # add some other names
    # problem_names.extend(["imo_2007_p6"])
    # print(len(problem_names))

    return problem_names
def recursive_extract(input,find,array_string=""):
    if find in input:
        if find=="```isabelle":
            find_index=input.find(find)

            return recursive_extract(input[find_index+len(find):],"```",array_string)
        elif find=="```":
            find_index = input.find(find)
            array_string = "{}\n\n{}".format(array_string,input[:find_index] )
            return recursive_extract(input[find_index+len(find):],"```isabelle",array_string)
    else:
        if len(array_string)==0:
            return input
        else:
            return array_string
def get_finish(args,only_success=False):
    if os.path.exists(os.path.join(args.dump_path, "success")):
        problem_names = [f[:f.rindex("_")] for f in os.listdir(os.path.join(args.dump_path, "success")) if os.path.isfile(os.path.join(args.dump_path, "success", f))]
    else:
        problem_names=[]

    if only_success:
        return problem_names
    # add some other names
    if os.path.exists(os.path.join(args.dump_path, "failure")):
        problem_names.extend( [f[:f.rindex("_")] for f in os.listdir(os.path.join(args.dump_path, "failure")) if os.path.isfile(os.path.join(args.dump_path, "failure", f))] )


    return problem_names

# proxies = {
#     'http': "http://10.90.91.205:3128",
# 'https': "http://10.90.91.205:3128"}
# openai.proxy = proxies

def add_json_dict(json_path, key, obj):
    '''
    Add an object into a json file of dictionary  {key: list of objects}
    :param json_path: path to the json file (which should be a dict)
    :param key: the key to which the obj belongs
    :param obj: object to be appended
    :return: None
    '''
    # count_fail=0
    # while count_fail<10:
    #     try:
    #         if os.path.exists(json_path):
    #             with open(json_path) as f:
    #                 json_data = json.load(f)
    #         else:
    #             json_data = {}
    #         if key in json_data:
    #             json_data[key].append(obj)
    #         else:
    #             json_data[key] = [obj]
    #         with open(json_path, "w") as f:
    #             json.dump(json_data, f, indent=2)
    #         break
    #     except Exception as e:
    #         print(str(e))
    #         print("Fail to Add Json dict: {}".format(count_fail))
    #         count_fail=count_fail+1
    #         time.sleep(2)

    if os.path.exists(json_path):
        with open(json_path) as f:
            json_data = json.load(f)
    else:
        json_data = {}
    if key in json_data:
        json_data[key].append(obj)
    else:
        json_data[key] = [obj]
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2)


def func_query_and_store(json_obj):
    tag = json_obj["tag"]
    header = json_obj["isa_header"]
    prompt_sample = json_obj["prompt_sample"]
    generation_params = json_obj["generation_params"]
    hashed_id = json_obj["hashed_id"]
    prompt_examples = json_obj["prompt_examples"]
    problem = json_obj["problem"]
    dump_path = json_obj["dump_path"]
    SLURM_ARRAY_TASK_ID=json_obj["SLURM_ARRAY_TASK_ID"]
    isa_completor = json_obj.get("completor", None)

    return a_single_job(
        tag,
        header,
        prompt_sample,
        generation_params,
        hashed_id,
        prompt_examples,
        problem,
        dump_path,
        SLURM_ARRAY_TASK_ID,
        isa_completor,
        json_obj,
    )

random.seed(213)
boxed_string = "\\boxed{"
theorem_string = "theorem"
oai_keys = [
""
]
oai_org = "org-kuQ09yewcuHU5GN5YYEUp2hh"
informal_starter = "Informal:\n(*"
informal_statement_starter = "### Problem"
informal_proof_starter = "### Solution"
formal_statement_starter = "Formal:"

prompts_path = "draft_data/paper_prompt_examples/"
prompts_by_category = {}
for prompt_file in os.listdir(prompts_path):
    if prompt_file.endswith("json"):
        prompt_file_path = os.path.join(prompts_path, prompt_file)
        prompt_json = json.load(open(prompt_file_path))
        tag = prompt_json["tag"]
        category = prompt_json["category"]
        prompt = prompt_json["prompt"]
        
        if category not in prompts_by_category:
            prompts_by_category[category] = {}
            
        prompts_by_category[category][tag] = prompt.strip()

def generate(prompt, n=1, temperature=0.0, max_tokens=1024, failure_limit=50, failure_sleep=5):
    while True:
        # import openai
        openai.api_key = ""
        print(prompt)
        try:
            completion = openai.Completion.create(
                model='code-davinci-002',
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                n=n,
                stop=['\n\n'],
            )
            break
        except Exception as e:
            failure_limit -= 1
            if failure_limit == 0:
                print("too many failures, giving up")
                return ['']
            print(str(e))
            print("Retrying... (%d retries remaining)" % failure_limit)
            time.sleep(failure_sleep)

    texts = [choice['text'] for choice in completion['choices']]
    return texts


def generate_multi(prompt, n=1, temperatures=[0.0], max_tokens=1024, sleep=0):
    texts = []
    settings = [(1, 0.0)] + [(n, temp) for temp in temperatures]
    for (num_samples, temp) in settings:
        if num_samples > 0:
            texts_ = generate(
                prompt=prompt, n=num_samples, temperature=temp, max_tokens=max_tokens
            )
            texts.extend(texts_)
            if sleep > 0:
                time.sleep(sleep)
    return texts


def ad_hoc_generate(prompt, max_tokens=256, stop_sequence='\n\n', temperature=0.0):
    completion = openai.Completion.create(
        model='code-davinci-002',
        prompt=prompt,
        max_tokens=max_tokens,
        stop=[stop_sequence],
        temperature=temperature
    )
    return completion['choices'][0]['text']


def get_info_from_response_path(response_path):
    with open(response_path) as f:
        response = json.load(f)
    return {
        "id": response["id"],
        "theorem": response["problem"]["formal_statement"],
        "proof": response["generation"].strip(),
        "generation_params": response["generation_params"],
    }

def find_available_port():
    SLURM_ARRAY_TASK_ID = os.environ.get("SLURM_ARRAY_TASK_ID", None)
    SLURM_ARRAY_TASK_ID = int(SLURM_ARRAY_TASK_ID)
    assert isinstance(SLURM_ARRAY_TASK_ID, int), SLURM_ARRAY_TASK_ID
    assert SLURM_ARRAY_TASK_ID >= 0
    assert SLURM_ARRAY_TASK_ID <= 10000
    
    available_ports = [8000, 9000, 10000, 11000, 12000, 13000, 14000, 15000, 16000, 17000]
    modulo_residue = SLURM_ARRAY_TASK_ID % len(available_ports)
    # Rotate the available ports so that the first port is different for different jobs
    available_ports = available_ports[modulo_residue:] + available_ports[:modulo_residue]

    for port in available_ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('localhost', port))
        if result != 0:
            sock.close()
            return port
    raise AssertionError


def sample_prompts(prompts_by_category, category, n=3, avoid_tag=None):
    # Sample n prompts and give their tags
    if category not in prompts_by_category:
        # print(prompts_by_category["algebra"])
        # print(prompts_by_category["number_theory"])
        prompts = prompts_by_category["algebra"]|prompts_by_category["number_theory"]
    else:
        prompts = prompts_by_category[category]
    
    tags = list(prompts.keys())
    if isinstance(avoid_tag, str):
        tags = [element for element in tags if element != avoid_tag]
    sampled_tags = random.sample(tags, k=n)

    processed_sampled_prompts = []
    for tag in sampled_tags:
        sampled_prompt = prompts[tag].strip()
        if "*)\n\nFormal:" in sampled_prompt:
            index = sampled_prompt.find("*)\n\nFormal:")
            if sampled_prompt[index-1] == "\n":
                sampled_prompt = sampled_prompt[:index-1] + sampled_prompt[index:]
        elif "\n\nFormal:" in sampled_prompt:
            index = sampled_prompt.find("\n\nFormal:")
            if sampled_prompt[index-1] == "\n":
                sampled_prompt = sampled_prompt[:index-1] + sampled_prompt[index:]
        else:
            pass
        
        processed_sampled_prompts.append(sampled_prompt)
    
    prompt_string = "\n\n".join(processed_sampled_prompts)
    return prompt_string, sampled_tags

def type_conversion(problem_type):
    return {
        "Algebra": "algebra",
        "Number Theory": "number_theory",
    }[problem_type]

def get_the_type(tag):
    if "algebra" in tag:
        return "algebra"
    elif "number_theory" in tag:
        return "number_theory"
    else:
        return "unknown"

def extract_boxed_content_and_indices(proof_string):
    starting_index = proof_string.find(boxed_string)
    opening_brackets = 0
    for i in range(starting_index+len(boxed_string), len(proof_string)):
        if proof_string[i] == "}":
            if opening_brackets == 0:
                return proof_string[starting_index+len(boxed_string):i], \
                        (starting_index, i)
            else:
                opening_brackets -= 1
        elif proof_string[i] == "{":
            opening_brackets += 1
        else:
            pass
        
def process_formal_statements(formal_statement):
    if len(formal_statement.split()) == 0:
        pass
    else:
        if not theorem_string in formal_statement.split()[0]:
            print(formal_statement)
    starting_index = formal_statement.find(theorem_string) + len(theorem_string)
    colon_index = formal_statement.find(":")
    return formal_statement[:starting_index] + formal_statement[colon_index+1:]

def process_prompt_examples(
    prompts_by_type, 
    omit_informal_statement=False,
    omit_informal_proof=False,
    omit_formal=False,
):
    if "omission_done" not in prompts_by_type and (omit_informal_statement or omit_informal_proof or omit_formal):
        for category, category_prompt_dict in prompts_by_type.items():
            for tag, prompt in category_prompt_dict.items():
                divided_elements = re.split(f"{informal_statement_starter}|{informal_proof_starter}|{formal_statement_starter}", prompt)
                assert len(divided_elements) == 4, divided_elements
                assert divided_elements[0] == informal_starter, divided_elements[0]

                assembled_string = ""
                if not omit_informal_statement:
                    assembled_string += informal_starter + informal_statement_starter + divided_elements[1]
                if not omit_informal_proof:
                    assembled_string += informal_proof_starter + divided_elements[2]
                if not omit_formal:
                    assembled_string += formal_statement_starter + divided_elements[3]
                prompts_by_type[category][tag] = assembled_string
    prompts_by_type["omission_done"] = True
    return prompts_by_type


def get_a_single_sample(
    informal_statement, informal_proof, 
    formal_statement, problem_type, tag, 
    n=3, 
    delete_comments=False,
    prompts_type="default",
    omit_informal_statement=False,
    omit_informal_proof=False,
    omit_formal=False,
    codex_generation=False,
):
    prompts_by_type = {
        "default": copy.deepcopy(prompts_by_category),
        # "ablation": ablation_prompts_by_category,
        # "ablation_sketch": ablation_sketch_prompts_by_category,
    }[prompts_type]


    prompts_by_type = process_prompt_examples(
        prompts_by_type,
        omit_informal_statement=omit_informal_statement,
        omit_informal_proof=omit_informal_proof,
        omit_formal=omit_formal,
    )
    proper_prefix = False

    if len(informal_proof) > 5000:  #chunk informal proof len
        informal_proof = informal_proof[:5000]
    while not proper_prefix:
        prompt_prefix, sampled_tags = sample_prompts(prompts_by_type, problem_type, n=n, avoid_tag=tag)
        if len(prompt_prefix) + len(informal_statement) + len(informal_proof) <= 10000:  #set prompt len limit
            proper_prefix = True
    
    if delete_comments:
        prompt_prefix_lines = [line.strip() for line in prompt_prefix.split("\n")]
        lines_to_delete = []
        to_delete = False
        for i, line in enumerate(prompt_prefix_lines):
            
            if line.startswith("(*"):
                assert not to_delete
                to_delete = True
            
            if to_delete:
                lines_to_delete.append(i)

            if line.endswith("*)"):
                assert to_delete
                to_delete = False
        assert not to_delete
        prompt_prefix_lines = [line for i, line in enumerate(prompt_prefix_lines) if i not in lines_to_delete]
        prompt_prefix = "\n".join(prompt_prefix_lines)

    if boxed_string in informal_proof:
        result = extract_boxed_content_and_indices(informal_proof)
        if result is None:
            pass
        else:
            content, (si, ei) = result
            content = content.strip()
            if "Show that it is" not in informal_statement:
                informal_statement = f"{informal_statement.strip()} Show that it is {content}."
            informal_proof = informal_proof[:si] + content + informal_proof[ei+1:]
    
    formal_statement = process_formal_statements(formal_statement)
    if not codex_generation:
        total_prompt = f"{prompt_prefix}\n\n" + \
            f"Informal:\n(*" + \
            ("" if omit_informal_statement else f"{informal_statement_starter}\n\n{informal_statement}\n\n") + \
            ("" if omit_informal_proof else f"{informal_proof_starter}\n\n{informal_proof}*)\n\n") + \
            ("" if omit_formal else f"{formal_statement_starter}\n{formal_statement}")

    else:
        total_prompt = f"{prompt_prefix}\n\n" + \
            f"Informal:\n(*" + \
            ("" if omit_informal_statement else f"{informal_statement_starter}\n\n{informal_statement}\n\n") + \
            ("" if False else f"{informal_proof_starter}")
    return total_prompt, sampled_tags

def a_single_job(
    tag,
    header,
    prompt_sample, 
    generation_params, 
    hashed_id, 
    prompt_examples, 
    problem, 
    dump_path,
    SLURM_ARRAY_TASK_ID,
    isa_completor=None,
    json_obj_ori=None,
):
    os.system("bash set_network.bash")
    index = 0
    success = False
    repeat_time = 0
    response=None
    result, output = None, None
    while (not success):
        if not os.path.exists(os.path.join(dump_path, "continue.txt")):
            raise ValueError("Not File {}".format(dump_path))
        try:
            print(prompt_sample)
            key = oai_keys[index]
            # import openai
            openai.api_key = key
            # if oai_org is not None:
            #     openai.organization = oai_org

            print("===")
            print(generation_params)
            if generation_params["model"] in ["gpt-3.5-turbo","gpt-3.5-turbo-16k", "gpt-4"]:
                if json_obj_ori['error'] is None or json_obj_ori['args'].method=='dsp':
                    print("Utilize DSP")
                    client = OpenAI(
                        # This is the default and can be omitted
                        api_key="",
                    )

                    json_obj =  client.chat.completions.create(
                                messages=[
                                    {"role": "system",  "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                                    {"role": "user", "content": prompt_sample.strip()}
                                         ],
                                **generation_params
                            )

                    client.close()


                    # json_obj = openai.ChatCompletion.create(
                    #             messages=[
                    #                 {"role": "system",  "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                    #                 {"role": "user", "content": prompt_sample.strip()}
                    #                      ],
                    #             **generation_params
                    #         )

                else:
                    # prompt_sample_list=

                    client = OpenAI(
                        # This is the default and can be omitted
                        api_key="",
                    )



                    json_obj =  client.chat.completions.create(

                        # {"role": "system",
                        #  "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                        # # {"role": "system",
                        # # "content": "Follow the given examples and complete the proof with Isabelle"},
                        # {"role": "user", "content": prompt_sample.strip()},
                        # {"role": "assistant", "content": json_obj_ori['previous_response'].strip()},
                        # {"role": "user",
                        #  "content": "(*The last proof has the following errors from Isabelle Prover. Therefore,\n1) Please Follow  the Above Prompt;\n\n2) And Utilize the Following Errors to redo the last formal proof.\n{};\n\n3) Please Stricly Complete the Proof with Ibsabelle Syntex.\n\n*)\n\n proof -\n".format(
                        #      json_obj_ori['error'])}
                                messages=[
                                    {"role": "system", "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                                    # {"role": "system",
                                     # "content": "Follow the given examples and complete the proof with Isabelle"},
                                             {"role": "user", "content": prompt_sample.strip()},
                                    {"role": "assistant", "content": json_obj_ori['previous_response'].strip()},
                                    {"role": "user", "content": "(*The last proof has the following errors from Isabelle Prover. Therefore,\n 1) Please Follow  the Above Prompt;\n\n 2) And Utilize the Following Errors to redo the last formal proof.\n {}.\n\n*)\n\n proof -\n".format(json_obj_ori['error'])}
                                         ],
                                **generation_params
                            )

                    client.close()


                    # json_obj = openai.ChatCompletion.create(
                    #
                    #     # {"role": "system",
                    #     #  "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                    #     # # {"role": "system",
                    #     # # "content": "Follow the given examples and complete the proof with Isabelle"},
                    #     # {"role": "user", "content": prompt_sample.strip()},
                    #     # {"role": "assistant", "content": json_obj_ori['previous_response'].strip()},
                    #     # {"role": "user",
                    #     #  "content": "(*The last proof has the following errors from Isabelle Prover. Therefore,\n1) Please Follow  the Above Prompt;\n\n2) And Utilize the Following Errors to redo the last formal proof.\n{};\n\n3) Please Stricly Complete the Proof with Ibsabelle Syntex.\n\n*)\n\n proof -\n".format(
                    #     #      json_obj_ori['error'])}
                    #             messages=[
                    #                 {"role": "system", "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                    #                 # {"role": "system",
                    #                  # "content": "Follow the given examples and complete the proof with Isabelle"},
                    #                          {"role": "user", "content": prompt_sample.strip()},
                    #                 {"role": "assistant", "content": json_obj_ori['previous_response'].strip()},
                    #                 {"role": "user", "content": "(*The last proof has the following errors from Isabelle Prover. Therefore,\n 1) Please Follow  the Above Prompt;\n\n 2) And Utilize the Following Errors to redo the last formal proof.\n {}.\n\n*)\n\n proof -\n".format(json_obj_ori['error'])}
                    #                      ],
                    #             **generation_params
                    #         )


            # print(json_obj)
            # print("=== response ===")
            #     response = json_obj["choices"][0]["message"]["content"]
                response = json_obj.choices[0].message.content
            else:
                json_obj = json.loads(
                    str(
                        openai.Completion.create(prompt=prompt_sample.strip(),
                                **generation_params
                        )
                    )
                )
                response = json_obj["choices"][0]["text"]
            print(response)

            # if json_obj_ori['args'].codex_generation:
            #     if not "Formal:" in response :
            #         time.sleep(65)
            #         continue
            #     else:
            #         response_list=response.split("Formal:")
            #         response = response_list[1].strip()

            ### PostProcess
            if not (json_obj_ori['error'] is None or json_obj_ori['args'].method == 'dsp'):
                response=recursive_extract(response,"```isabelle","")

            if (not response.strip().startswith("using")):
                if response.strip().count("proof -")+response.strip().count("proof (")+response.strip().count("proof(")+response.strip().count("proof \n")+response.strip().count("proof\n") == response.strip().count("qed"):
                    if (not response.strip().startswith("lemma")) :


                        response_index = response.find("proof -")
                        response_index_2 = response.find("proof (")

                        if response_index!=-1:
                            response = response[response_index:]

                        elif response_index_2!=-1:
                            response = response[response_index_2:]
                        else:
                            response = response

                        if response.strip().startswith("proof\n"):
                            response_index = response.find("proof\n")
                            response = "proof -\n"+response[response_index+len("proof\n"):]
                        elif response.strip().startswith("proof \n"):
                            response_index = response.find("proof \n")
                            response = "proof -\n"+response[response_index+len("proof \n"):]

                else:
                    if not response.strip().startswith("proof -"):
                        if response.strip().startswith("("):
                            response = "proof -\n"+response
                        elif response.strip().startswith("lemma"):
                            response=response
                        elif response.strip().startswith("proof\n"):
                            response_index = response.find("proof\n")
                            response = "proof -\n"+response[response_index+len("proof\n"):]
                        elif response.strip().startswith("proof \n"):
                            response_index = response.find("proof \n")
                            response = "proof -\n"+response[response_index+len("proof \n"):]
                        else:
                            # response_index = response.find("proof \n")
                            response = "proof -\n"+response

            ### PostProcess
                            # if (not response.strip().startswith("proof")) and (not response.strip().startswith("(")) and (not response.strip().startswith("using"))  and (not response.strip().startswith("lemma")):
                #     if response.strip().count("proof -")==response.strip().count("qed"):
                #         response_index=response.find("proof -")
                #         response=response[response_index:]
                #     else:
                #         response="proof -\n"+response
                # elif (not response.strip().startswith("proof")) and response.strip().count("proof -")!=response.strip().count("qed"):
                #     response = "proof -\n" + response

            # if not (json_obj_ori['error'] is None or json_obj_ori['args'].method=='dsp'):
            #     index_first=response.find("proof")
            #     response=response[index_first:]
                # response=response.replace("")

            # print(response)
            print("=== end ===")
            success = True
        except Exception as e:
            print(f"Generation error: {index}")
            print(e)
            print(e.__traceback__)
            index = (index + 1) % len(oai_keys)
            repeat_time += 1
            time.sleep(65)
    if success:
        result_json_path = os.path.join(dump_path, "generation_json_dict_{}.json".format(SLURM_ARRAY_TASK_ID))
        print(result_json_path)
        result_dict = {
            "tag": tag,
            "id": hashed_id,
            "prompt_examples": prompt_examples,
            "generation_params": generation_params,
            "problem": problem,
            "generation": response,
            "isa_header":header
        }
        add_json_dict(
            result_json_path,
            tag,
            result_dict,
        )

        print("tag: {}".format(tag))
        if isa_completor is not None:
            # step1 extract to file
            sketch_dir = os.path.join(dump_path,"result", tag, "problem_sketch/")
            sketch_path = extract_generated_to_file(sketch_dir, tag, result_dict)

            # step2 use ProofCompletorISA to check proof and return error msg
            print("######### verifying result ##################")
            result, output = isa_completor.complete(
                tag, 
                sketch_file=os.path.abspath(sketch_path), 
                init_from_original=False
            )
            if len(output)==0:
                output["error"]="None"
            error_msg = output["error"]
            print("Error: {} {}\n".format(result,output) )
            print("######### verifying end ##################")
        else:
            result, output=None,None
            
    return success, response, result, output


def a_single_job_informal(
        prompt_sample,
        generation_params,
        dump_path,
):
    os.system("bash set_network.bash")
    index = 0
    success = False
    repeat_time = 0
    response = None
    result, output = None, None
    while (not success):
        if not os.path.exists(os.path.join(dump_path, "continue.txt")):
            raise ValueError("Not File {}".format(dump_path))
        try:
            print(prompt_sample)
            key = oai_keys[index]
            # import openai
            openai.api_key = key
            # if oai_org is not None:
            #     openai.organization = oai_org

            print("===")
            print(generation_params)

            # openai.proxy = proxies
            if generation_params["model"] in ["gpt-3.5-turbo", "gpt-3.5-turbo-16k", "gpt-4"]:
                print("Generate Informal")

                client = OpenAI(
                    # This is the default and can be omitted
                    api_key="",
                )

                json_obj = client.chat.completions.create(
                        messages=[
                            # {"role": "system",
                            #  "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                            {"role": "user", "content": prompt_sample.strip()}
                        ],
                        **generation_params
                    )

                client.close()
                response = json_obj.choices[0].message.content


                # json_obj = openai.ChatCompletion.create(
                #     messages=[
                #         # {"role": "system",
                #         #  "content": "You are an expert in Mathmatical Proof and Isabelle Proof Assistant. Follow the given examples and complete the proof with Isabelle Proof Assistant"},
                #         {"role": "user", "content": prompt_sample.strip()}
                #     ],
                #     **generation_params
                # )
                # response = json_obj["choices"][0]["message"]["content"]
            else:
                json_obj = json.loads(
                    str(
                        openai.Completion.create(prompt=prompt_sample.strip(),
                                                 **generation_params
                                                 )
                    )
                )
                response = json_obj["choices"][0]["text"]
            print(response)
            if response.strip().endswith("*)\n\n"):
                find_index=response.rfind("*)\n\n")
                response=response[:find_index]
            elif response.strip().endswith("*)\n"):
                find_index = response.rfind("*)\n")
                response = response[:find_index]
            elif response.strip().endswith("*)"):
                find_index = response.rfind("*)")
                response = response[:find_index]
            elif response.strip().endswith("*"):
                find_index = response.rfind("*")
                response = response[:find_index]
            else:
                response = response
            print("=== After Process Informal ===")
            print(response)
            print("=== Process Informal end ===")
            success = True
        except Exception as e:
            print(f"Generation error: {index}")
            print(e)
            index = (index + 1) % len(oai_keys)
            repeat_time += 1
            time.sleep(65)

    return success, response

def extract_generated_to_file(output_dir, problem_name, content):
    
    # # open miniF2F data
    # with open("draft_data/minif2f.json", "r", encoding='utf-8') as f:
    #     miniF2F_data = json.load(f)
    #
    # raw_name = problem_name
    # if "_genproof" in problem_name:
    #     raw_name = problem_name[:problem_name.find("_genproof")]
    #
    # header = miniF2F_data[raw_name]['isa_header']

    header=content['isa_header']

    statement = content['problem']['formal_statement']
    generated = content['generation']

    save_path = os.path.join(output_dir, f"{problem_name}_sketch0.thy")

    if not os.path.exists(os.path.dirname(save_path)):
        os.makedirs(os.path.dirname(save_path))
    
    with open(save_path, "w", encoding='utf-8') as f:
        file_text = header + "(*statement begin*)\n" + statement + "(*statement end*)\n" + generated + "\nend\n"

        print(file_text)
        f.write(file_text)
    
    return save_path


def a_list_of_jobs(
    list_of_parameters,
    progress_path="/large_experiments/theorem/aqj/dumped/experiment_09_07/progress",
    good_count=0,length=0
):
    # SLURM_ARRAY_TASK_ID = os.environ.get("SLURM_ARRAY_TASK_ID", None)
    # SLURM_ARRAY_TASK_ID = int(SLURM_ARRAY_TASK_ID)

    # progress_file_path = os.path.join(
    #     progress_path,
    #     f"progress_{SLURM_ARRAY_TASK_ID}.txt",
    # )
    SLURM_ARRAY_TASK_ID = os.getpid()
    SLURM_ARRAY_TASK_ID = int(SLURM_ARRAY_TASK_ID)

    progress_file_path = os.path.join(
        progress_path,
        f"progress_{SLURM_ARRAY_TASK_ID}.txt",
    )
    if not os.path.exists(progress_path):
        os.makedirs(progress_path)
    # progress_file_path = os.path.join(
    #     progress_path,
    #     f"progress.txt",
    # )
    for tag, prompt_sample, generation_params, hashed_id, prompt_examples, problem, dump_path in list_of_parameters:
        print("{}/{}".format(good_count,length))
        param_json ={"tag": tag,
                     "prompt_sample": prompt_sample,
                     "generation_params": generation_params,
                     "hashed_id": hashed_id,
                     "prompt_examples": prompt_examples,
                     "problem": problem,
                     "dump_path": dump_path,
                     "SLURM_ARRAY_TASK_ID":SLURM_ARRAY_TASK_ID
                    }
        param_json_path = os.path.join(dump_path, "param_json_dict_{}.json".format(SLURM_ARRAY_TASK_ID))
        failed_json_path = os.path.join(dump_path, "failed_param_json_dict_{}.json".format(SLURM_ARRAY_TASK_ID))
        # param_json_path = os.path.join(dump_path, f"param_{tag}_{hashed_id}.json")
        # with open(param_json_path, "w") as f:
        #     json.dump(
        #         {
        #             "tag": tag,
        #             "prompt_sample": prompt_sample,
        #             "generation_params": generation_params,
        #             "hashed_id": hashed_id,
        #             "prompt_examples": prompt_examples,
        #             "problem": problem,
        #             "dump_path": dump_path
        #         },
        #         f
        #     )
        success = func_query_and_store(param_json)
        if success:
            add_json_dict(param_json_path, tag, param_json)
            good_count += 1
            with open(progress_file_path, "w") as f:
                f.write(f"{good_count}\n")
        else:
            add_json_dict(failed_json_path, tag, param_json)
        time.sleep(10)
        # print("")

def a_single_problem_interact(
    problem_rank,
    problem_name,
    args=None,
    good_count=0,
    length=0,
):
    SLURM_ARRAY_TASK_ID = int(os.getpid())
    # print(problem_rank)
    print(problem_name)
    # print(args)
    problem_name=problem_name
    os.makedirs(os.path.join(args.dump_path, problem_name), exist_ok=True)

    # progress_file_path = os.path.join(args.dump_path, problem_name, f"progress_{SLURM_ARRAY_TASK_ID}.txt")

    output=None
    info = args.name_to_info[problem_name]
    with open(args.aligned_path, encoding='utf-8') as f:
        minif2f_data = json.load(f)
    header = minif2f_data[problem_name]['isa_header']
    statement = info["formal_statement"]

    # init PISA env
    print("Initializing PISA environment...")
    sketch_dir = os.path.join(args.dump_path,"result", problem_name, "problem_sketch/")
    os.makedirs(sketch_dir, exist_ok=True)
    isa_completor = init_isa_env(sketch_dir, problem_rank,postprocess=args.postprocess)
    isa_completor.reset_formal_system()

    update_freq=args.update_freq
    generation_params = {
        "temperature": args.temperature,
        "model": args.model,
        # "max_tokens": 1024,
        "stop": "Informal:",
        # "request_timeout": 3600,
    }

    count_try=0
    while count_try <args.n_attempts:
        # try:
        print(f"Trying {count_try}/{args.n_attempts}...")
        hashed_id = hash(f"{problem_name}-{count_try}")


        if args.codex_generation:
            if count_try%args.codex_generation_update==0:
                prompt_sample, sampled_problem_names = get_a_single_sample(
                    info["informal_statement"],
                    info["informal_proof"],
                    info["formal_statement"],
                    get_the_type(problem_name),
                    problem_name,
                    prompts_type=args.prompts_type,
                    n=args.n_examples,
                    omit_informal_statement=args.omit_informal_statement,
                    omit_informal_proof=False,
                    omit_formal=True,
                    codex_generation=args.codex_generation,
                )
                generation_params_informal = {
                    "temperature": args.temperature,
                    "model": args.model,
                    # "max_tokens": 1024,
                    "stop": "Formal:",
                    # "request_timeout": 3600,
                }
                while True:
                    success_informal,response_informal=a_single_job_informal(prompt_sample,generation_params_informal,args.dump_path)
                    if success_informal:
                        break


            prompt_sample, sampled_problem_names = get_a_single_sample(
                info["informal_statement"],
                response_informal,
                info["formal_statement"],
                get_the_type(problem_name),
                problem_name,
                prompts_type=args.prompts_type,
                n=args.n_examples,
                omit_informal_statement=args.omit_informal_statement,
                omit_informal_proof=args.omit_informal_proof,
                omit_formal=args.omit_formal,
                codex_generation=False,
            )
            prompt_examples = sampled_problem_names
            problem = {
                "tag": problem_name,
                "informal_statement": info["informal_statement"],
                "informal_proof": response_informal,
                "formal_statement": info["formal_statement"],
            }


        else:


            prompt_sample, sampled_problem_names = get_a_single_sample(
                info["informal_statement"],
                info["informal_proof"],
                info["formal_statement"],
                get_the_type(problem_name),
                problem_name,
                prompts_type=args.prompts_type,
                n=args.n_examples,
                omit_informal_statement=args.omit_informal_statement,
                omit_informal_proof=args.omit_informal_proof,
                omit_formal=args.omit_formal,
                codex_generation=args.codex_generation,
            )

            prompt_examples = sampled_problem_names
            problem = {
                "tag": problem_name,
                "informal_statement": info["informal_statement"],
                "informal_proof": info["informal_proof"],
                "formal_statement": info["formal_statement"],
            }









        if output!=None:
            prompt_sample_split=prompt_sample.split("Informal:")
            prompt_sample_this_question="Informal:"+prompt_sample_split[-1]
            if output['error']=="None":
                prompt_with_feedback = "Error Message Summary: {}\n".format(result)
            else:
                # prompt_with_feedback = "(*We give you the following question's potentiel proof and error message. Please refer to the above prompt and the following question's potentiel proof and error message to complete the Isabelle proof. Note: Do Not Copy and Paste the potentiel proof, but just for reference." \
                #                        "Potential Proof: \n{}\n" \
                #                        "Potential Proof Error Message Summary: {}\n" \
                #                        "*Error Message Detail Begin: {}\n*Potential Proof Error Message Detail End\n" \
                #                        "Please use the above prompt and the question's potentiel proof and error message to complete the Isabelle proof, but do not copy and paste the potential proof*)\n\n".format(generated,
                #     result, output['error'].replace("\n", ""))

                prompt_with_feedback = "Error Tactic: {}\nError Message Summary: {}\n" \
                                       "Error Message Detail: {}\n".format(
                    output['tactic_info'],result, output['error'].replace("\n", ""))
            print(prompt_with_feedback)

            # if args.method=="dsp":
            #     prompt_sample = prompt_sample
            # else:
            #     prompt_sample=prompt_sample.replace(prompt_sample_this_question,"")
            #     prompt_sample=prompt_sample









        if args.method == "dsp" or output==None or (count_try%update_freq)==0:
            param_json = {"tag": problem_name,
                          "prompt_sample": prompt_sample,
                          "generation_params": generation_params,
                          "hashed_id": hashed_id,
                          "prompt_examples": prompt_examples,
                          "problem": problem,
                          "dump_path": args.dump_path,
                          "SLURM_ARRAY_TASK_ID": SLURM_ARRAY_TASK_ID,
                          "completor": isa_completor,
                          "isa_header": header,
                          "args": args,
                          "error": None
                          }
        else:
            param_json = {"tag": problem_name,
                          "prompt_sample": prompt_sample,
                          "generation_params": generation_params,
                          "hashed_id": hashed_id,
                          "prompt_examples": prompt_examples,
                          "problem": problem,
                          "dump_path": args.dump_path,
                          "SLURM_ARRAY_TASK_ID": SLURM_ARRAY_TASK_ID,
                          "completor": isa_completor,
                          "isa_header": header,
                          "args": args,
                          "error":prompt_with_feedback,
                          "previous_response":generated
                          }





        param_json_path = os.path.join(args.dump_path,problem_name, "param_json_dict_{}.json".format(SLURM_ARRAY_TASK_ID))
        failed_json_path = os.path.join(args.dump_path,problem_name, "failed_param_json_dict_{}.json".format(SLURM_ARRAY_TASK_ID))




        success, generated,result, output = func_query_and_store(param_json)
        if success:
            add_json_dict(param_json_path, problem_name, { key:param_json[key] for key in param_json.keys() & save_para_json_name })
            good_count += 1
            # with open(progress_file_path, "w") as f:
            #     f.write(f"{good_count}\n")
            #
            with open(os.path.join( args.dump_path,problem_name,"{}.thy".format(count_try)), "w", encoding='utf-8') as f:
                 f.write(header + "(*statement begin*)\n" + statement + "(*statement end*)\n" + generated + "\nend\n")
            if result=="success":
                with open(os.path.join( args.dump_path,"success","{}_{}.thy".format(problem_name,count_try)), "w", encoding='utf-8') as f:
                    f.write(header + "(*statement begin*)\n" + statement + "(*statement end*)\n" + generated + "\nend\n")
                isa_completor.kill()
                gc.collect()
                return


        else:
            add_json_dict(failed_json_path, problem_name, { key:param_json[key] for key in param_json.keys() & save_para_json_name })
        time.sleep(10)




        isa_completor.reset_search()
        if (count_try+1)%5==0:
            isa_completor.kill()
            isa_completor = init_isa_env(sketch_dir, problem_rank,postprocess=args.postprocess)
            isa_completor.reset_formal_system()

        gc.collect()

        count_try+=1
        # except Exception as e:
        #     print("Exception!")

    with open(os.path.join(args.dump_path, "failure", "{}_{}.thy".format(problem_name, count_try)), "w",
              encoding='utf-8') as f:
        f.write(header + "(*statement begin*)\n" + statement + "(*statement end*)\n" + generated + "\nend\n")
    isa_completor.kill()
    # gc.collect()
def a_list_problem_interact(
    problem_rank,
    # problem_name,
    args=None,
    # good_count=0,
    # length=0,
):
    # print(problem_name[0])
    # print(problem_rank)
    # print(problem_rank)
    # assert len(problem_rank)==len(problem_name),"{} {}".format( len(problem_rank),len(problem_name))
    # assert len(problem_rank) == len(args), "{} {}".format(len(problem_rank), len(args))

    # for i in range(len(problem_name)):
    #     a_single_problem_interact(problem_rank[i],problem_name[i],args[i])
    #     gc.collect()
    #
    while True:

        if not os.path.exists(os.path.join(args[0].dump_path, "continue.txt")):
            raise ValueError("Not File {}".format(args[0].dump_path))

        f = open(args[0].fileToFinish, 'rb+')
        lock(f)  # 加锁 print(f.read()) time.sleep(3)
        f_save = open(args[0].fileToFinish.replace(".txt",""), 'rb')
        file_list = pickle.load(f_save)
        f_save.close()
        f_save = open(args[0].fileToFinish.replace(".txt", ""), 'wb')

        if len(file_list) == 0:
            print("Finish")

            f_save.close()

            un_lock(f)
            f.close()
            gc.collect()
            break

        file_name = file_list.pop()
        print(file_list)
        pickle.dump(file_list, f_save)
        f_save.close()



        un_lock(f)
        f.close()
        a_single_problem_interact(problem_rank[0], file_name, args[0])
        gc.collect()

def init_isa_env(sketch_dir, rank, cache_dir="/home/chuanyang/cache/",postprocess=True):
    interactive_dir = os.path.join(sketch_dir, "interactive")
    os.makedirs(interactive_dir, exist_ok=True)

    ORIGINAL_DIR = "draft_data/isabelle"
    ORIGINAL_FILE_DICT = {} # problem_name: original_isabelle_file_path
    for _split in ['test','valid']:
        split_dir = os.path.join(ORIGINAL_DIR, _split)
        problem_list = get_problem_names(_split)
        for problem in problem_list:
            ORIGINAL_FILE_DICT[problem] = os.path.join(split_dir, problem+".thy")

    # proof completor
    completor = ProofCompletorISA(
        isa_gym_dir="isabelle_gym/",
        original_file_dict=ORIGINAL_FILE_DICT, 
        rank=rank,
        interactive_dir=os.path.abspath(interactive_dir),
        cache_dir=cache_dir,
        postprocess=postprocess
    )

    return completor






def a_single_problem_verify(
    problem_rank,
    problem_name,
    args=None,
    good_count=0,
    length=0,
):

    print(problem_name)
    # print(args)
    problem_name=problem_name
    # os.makedirs(os.path.join(args.dump_path, problem_name), exist_ok=True)

    # init PISA env
    print("Initializing PISA environment...")
    sketch_dir = os.path.join(args.dump_path,"result", problem_name, "problem_sketch/")
    # os.makedirs(sketch_dir, exist_ok=True)
    isa_completor = init_isa_env(sketch_dir, problem_rank,postprocess=args.postprocess)
    isa_completor.reset_formal_system()
    result, output = isa_completor.complete(
        problem_name,
        sketch_file=os.path.abspath(os.path.join(sketch_dir, f"{problem_name}_sketch0.thy")),
        init_from_original=False
    )

    isa_completor.kill()
    gc.collect()
    # gc.collect()
def a_list_problem_verify(
    problem_rank,
    # problem_name,
    args=None,
    # good_count=0,
    # length=0,
):
    # print(problem_name[0])
    # print(problem_rank)
    # print(problem_rank)
    # assert len(problem_rank)==len(problem_name),"{} {}".format( len(problem_rank),len(problem_name))
    # assert len(problem_rank) == len(args), "{} {}".format(len(problem_rank), len(args))

    # for i in range(len(problem_name)):
    #     a_single_problem_interact(problem_rank[i],problem_name[i],args[i])
    #     gc.collect()
    #
    while True:

        if not os.path.exists(os.path.join(args[0].dump_path, "continue.txt")):
            raise ValueError("Not File {}".format(args[0].dump_path))

        f = open(args[0].fileToFinish, 'rb+')
        lock(f)  # 加锁 print(f.read()) time.sleep(3)
        f_save = open(args[0].fileToFinish.replace(".txt",""), 'rb')
        file_list = pickle.load(f_save)
        f_save.close()
        f_save = open(args[0].fileToFinish.replace(".txt", ""), 'wb')

        if len(file_list) == 0:
            print("Finish")

            f_save.close()

            un_lock(f)
            f.close()
            gc.collect()
            break

        file_name = file_list.pop()
        print(file_list)
        pickle.dump(file_list, f_save)
        f_save.close()



        un_lock(f)
        f.close()
        a_single_problem_verify(problem_rank[0], file_name, args[0])
        gc.collect()
