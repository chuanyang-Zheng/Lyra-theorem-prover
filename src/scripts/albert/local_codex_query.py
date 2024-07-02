import os
import json
# import submitit
import argparse

import submitit
from tqdm import tqdm

from autoformalization.utils import get_the_type, get_a_single_sample, a_list_of_jobs, ROOTDIR

def list_file_name(directory):
    onlyfiles = [f.split(".")[0] for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    return onlyfiles

def get_test_file():
    test_all = list_file_name(os.path.join(ROOTDIR,"data/isabelle/test"))
    test_all.extend(["imosl_2007_algebra_p6"])

    return test_all


def prepare_generated_proof(generation_path):
    '''
    extract informal proofs from generation path as a dictionary:
        {problem_name: list of informal proofs}
    '''
    generation_path = os.path.join(generation_path, "generation_json_dict.json")
    with open(generation_path) as f:  #load generated data
        generation_json_dict = json.load(f)
    #extract generation into informal_proof
    generated_informal_proof = {}
    for problem_name, generation_info in generation_json_dict.items():
        generated_informal_proof[problem_name] = [x['generation'] for x in generation_info]
    return generated_informal_proof

def make_print_to_file(file_name='./', path="./"):
    '''
    path， it is a path for save your log about function print
    example:
    use  make_print_to_file()   and the   all the information of function print , will be write in to a log file
    :return:
    '''
    import os
    import sys
    import time
    import datetime
    import pytz

    class Logger(object):
        def __init__(self, filename, path="./"):
            self.terminal = sys.stdout
            self.log = open(filename, "w", encoding='utf8')

        def write(self, message):
            # self.terminal.write(message)
            if message != "\n" and message != "\r":
                message = str(datetime.datetime.now(pytz.timezone('Asia/Shanghai'))) + "   " + message

            self.terminal.write(message)
            self.log.write(message)
            self.log.flush()

        def flush(self):
            pass

    # fileName = time.strftime(file_name+'%Y-%m-%d %H:%M:%S',time.localtime(time.time()))
    sys.stdout = Logger(file_name, path=path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--aligned_path", type=str,
                        default="data/minif2f.json",
                        help="provide raw data including informal state, formal state and informal proof(optional)")
    parser.add_argument("--dump_path", type=str,
                        default="dump/sketch_imo_d100s1",
                        help="output directory")
    # parser.add_argument("--log_path", type=str, default="dump/first/log")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--n_examples", type=int, default=3, help="number of prompt examples")
    parser.add_argument("--prompts_type", type=str, default="default")
    parser.add_argument("--n_attempts", type=int, default=50)
    parser.add_argument("--chunk_size", type=int, default=610)
    parser.add_argument("--omit_informal_statement", action="store_true", default=False)
    parser.add_argument("--omit_informal_proof", action="store_true", default=False)
    parser.add_argument("--omit_formal", action="store_true", default=False)
    parser.add_argument("--codex_generation", action="store_true", default=False, help="whether generate informal proof or not")
    parser.add_argument("--generated_proof_path", type=str, default=None,
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--model", type=str, default="gpt-4",
                        help="path to the generated informal proofs. If None then use default proofs")

    args = parser.parse_args()
    args.log_path = os.path.join(args.dump_path, "log")
    args.progress_path = os.path.join(args.dump_path, "progress")
    print(args)
    # minerva_path = ""
    # minerva_dump_path = ""
    algined_path = os.path.join(ROOTDIR, args.aligned_path)
    dump_path = os.path.join(ROOTDIR, args.dump_path)
    print(dump_path)
    log_path = os.path.join(ROOTDIR, args.log_path)
    progress_path = os.path.join(ROOTDIR, args.progress_path)
    generated_proof_data = None
    if args.generated_proof_path is not None:
        assert (not args.codex_generation) and (not args.omit_informal_proof), \
            "when using generated proof, both codex_generation and omit_informal_proof should be False"
        generated_proof_data = prepare_generated_proof(os.path.join(ROOTDIR, args.generated_proof_path))
    prompts_type = args.prompts_type



    name_to_info = {}
    with open(algined_path) as f:
        metadata = json.load(f)
        for problem_name, line in metadata.items():
            # if not "imo" in problem_name: # only focus imo problems now
            #     continue
            informal_statement = line["informal_state"]
            informal_proof = line["informal_proof"]
            if isinstance(informal_proof, float):
                informal_proof = "We attempt this problem"

            formal_statement = line["isa_formal_state"] # isabelle formal statement

            informal_statement = informal_statement if not args.omit_informal_statement else ""
            informal_proof = informal_proof if not args.omit_informal_proof else ""
            if args.codex_generation:
                informal_proof = ""
            formal_statement = formal_statement if not args.omit_formal else ""
            if generated_proof_data is None:
                name_to_info[problem_name] = {
                    "informal_statement": informal_statement,
                    "informal_proof": informal_proof,
                    "formal_statement": formal_statement,
                }
            else:
                if not problem_name in generated_proof_data:
                    continue
                list_generated_proof = generated_proof_data[problem_name]
                for proof_id, informal_proof in enumerate(list_generated_proof):
                    name_to_info[f"{problem_name}_genproof_{proof_id}"] = {
                        "informal_statement": informal_statement,
                        "informal_proof": informal_proof,
                        "formal_statement": formal_statement,
                    }

    print(len(name_to_info))
    # assert len(name_to_info) == 488

    if not os.path.isdir(dump_path):
        os.makedirs(dump_path)

    index = 0
    temperature_schedule = [args.temperature] * args.n_attempts
    queries_per_tag = len(temperature_schedule)
    # todo: fix existing queries logic
    """
    existing_queries = dict()
    for file in os.listdir(dump_path):
        if file.endswith(".json") and not file.startswith("param"):
            tag = "_".join(file.split("_")[:-1])
            existing_queries[tag] = existing_queries.get(tag, 0) + 1

    for tag, count in existing_queries.items():
        if count == queries_per_tag:
            del name_to_info[tag]
        else:
            print(f"{dump_path}/{tag}_*.json")
            os.system(f"rm {dump_path}/{tag}_*.json")
    print(f"Number of remaining problems: {len(name_to_info)}")
    """

    generated_json_path = os.path.join(ROOTDIR, args.dump_path+".json")
    print(generated_json_path)
    if os.path.exists(generated_json_path):
        with open(generated_json_path) as f:
            generated_data = json.load(f)
        num_generated = {}
        for problem_id, generated in generated_data.items():
            num_generated[problem_id] = len(generated)

    make_print_to_file(os.path.join(dump_path,"log.txt"))
    number_of_queries = {}
    parameters = []


    test_files = get_test_file()
    count_finish=0
    print(count_finish)
    for i, (problem_name, info) in tqdm(enumerate(name_to_info.items())):



        if os.path.exists(generated_json_path):
            if num_generated.get(problem_name, 0)>=args.n_attempts:
                # print(num_generated.get(problem_name, 0))
                count_finish+=1
                print(count_finish)
                continue
            number_of_queries[problem_name]=num_generated.get(problem_name, 0)
            print(number_of_queries)



        if not problem_name in test_files:
            continue
        print(problem_name)
        for k in range(args.n_attempts-num_generated.get(problem_name, 0)):
            problem_name_index = number_of_queries.get(problem_name, 0)
            temperature = temperature_schedule[problem_name_index]
            number_of_queries[problem_name] = problem_name_index + 1
            hashed_id = hash(f"{problem_name}-{problem_name_index}")
            # if os.path.exists(generated_json_path):
            #     if problem_name_index < num_generated.get(problem_name, 0):
            #         continue
            prompt_sample, sampled_problem_names = get_a_single_sample(
                info["informal_statement"],
                info["informal_proof"],
                info["formal_statement"],
                get_the_type(problem_name),
                problem_name,
                prompts_type=prompts_type,
                n=args.n_examples,
                omit_informal_statement=args.omit_informal_statement,
                omit_informal_proof=args.omit_informal_proof,
                omit_formal=args.omit_formal,
                codex_generation=args.codex_generation,
            )
            # print(hashed_id)
            # print(prompt_sample)
            # print("="*100)
            # continue
            prompt_examples = sampled_problem_names
            generation_params = {
                "temperature": temperature,
                "model": args.model,
                # "max_tokens": 1024,
                "stop": "Informal",
                # "request_timeout": 3600,
            }
            problem = {
                "tag": problem_name,
                "informal_statement": info["informal_statement"],
                "informal_proof": info["informal_proof"],
                "formal_statement": info["formal_statement"],
            }
            parameters.append(
                (
                    problem_name,
                    prompt_sample,
                    generation_params,
                    hashed_id,
                    prompt_examples,
                    problem,
                    dump_path
                )
            )
    print(f"Number of queries: {len(parameters)}")
    # arg.chunk_size attempts per array job
    all_sub_lists = []
    for i in range(0, len(parameters), args.chunk_size):
        sub_list = parameters[i:i + args.chunk_size]
        all_sub_lists.append(sub_list)
    # assert len(all_sub_lists) < 500, len(all_sub_lists)

    length=len(parameters)
    print(len(all_sub_lists))
    print(len(all_sub_lists[0]))


    executor = submitit.AutoExecutor(folder=log_path)
    executor.update_parameters(
        slurm_array_parallelism=20,
        mem_gb=4,
        cpus_per_task=2,
        timeout_min=100*args.chunk_size,
        slurm_partition="Theorem_Proving,learnaccel",
        gpus_per_node=0,
    )
    good_count = 0

    print(args)
    if not os.path.exists(os.path.join(dump_path, "continue.txt")):
        with open(os.path.join(dump_path, "continue.txt"),"w") as f:
            f.write("AAA")
            f.flush()
    executor.map_array(a_list_of_jobs, all_sub_lists, [args.progress_path]*len(all_sub_lists))

    # for sub_lists in tqdm(all_sub_lists):
    #     a_list_of_jobs(sub_lists, progress_path, good_count=good_count,length=length)
    #     good_count += len(sub_lists)

