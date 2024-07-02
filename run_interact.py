import os
import json
import argparse
import pickle
import random

import submitit
from multiprocessing import Pool

from src.autoformalization.utils import a_single_problem_interact,get_problem_names,a_list_problem_interact,get_finish





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
    path: it is a path for save your log about function print
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
                        default="draft_data/minif2f_fix_isa.json",
                        help="provide raw data including informal state, formal state and informal proof(optional)")
    # miniF2F must exists in somewhere in the dump path
    parser.add_argument("--dump_path", type=str,
                        default="dump/miniF2F/",
                        help="output directory")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--n_examples", type=int, default=3, help="number of prompt examples")
    parser.add_argument("--prompts_type", type=str, default="default")
    parser.add_argument("--n_attempts", type=int, default=5)
    parser.add_argument("--chunk_size", type=int, default=1)
    parser.add_argument("--process_size", type=int, default=1)
    parser.add_argument("--omit_informal_statement", action="store_true", default=False)
    parser.add_argument("--omit_informal_proof", action="store_true", default=False)
    parser.add_argument("--omit_formal", action="store_true", default=False)
    parser.add_argument("--codex_generation", action="store_true", default=False, help="whether generate informal proof or not")
    parser.add_argument("--generated_proof_path", type=str, default=None,
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--model", type=str, default="gpt-4",
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--method", type=str, default="dsp",
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--start_rank", type=int, default=0,
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--fileToFinish", type=str, default="fileToFinish.txt",
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--postprocess", action='store_true',
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--update_freq", type=int,default=5,
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--split", type=str,default="test",
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--begin_success", type=int,default=0,
                        help="path to the generated informal proofs. If None then use default proofs")
    parser.add_argument("--codex_generation_update", type=int,default=5,
                        help="path to the generated informal proofs. If None then use default proofs")

    args = parser.parse_args()

    # if args.method=="dsp":
    #     args.update_freq=1

    if args.update_freq==1:
        args.codex_generation_update=1

    if args.update_freq==args.codex_generation_update:
        args.dump_path = "{}_Split{}_Postprocess{}_Genration{}_Update{}_Sketch{}_Temp{}_{}".format(args.dump_path,args.split,args.postprocess,args.codex_generation,args.update_freq,args.n_attempts,args.temperature,args.method)
    else:
        args.dump_path = "{}_Split{}_Postprocess{}_Genration{}{}_Update{}_Sketch{}_Temp{}_{}".format(args.dump_path,
                                                                                                   args.split,
                                                                                                   args.postprocess,
                                                                                                   args.codex_generation,
                                                                                                   args.codex_generation_update,
                                                                                                   args.update_freq,
                                                                                                   args.n_attempts,
                                                                                                   args.temperature,
                                                                                                   args.method)
    args.log_path = os.path.join(args.dump_path, "log")
    args.progress_path = os.path.join(args.dump_path, "progress")
    print(args)


    os.makedirs(args.dump_path, exist_ok=True)
    
    # -- load generated proof
    generated_proof_data = None
    # if args.generated_proof_path is not None:
    #     assert (not args.codex_generation) and (not args.omit_informal_proof), \
    #         "when using generated proof, both codex_generation and omit_informal_proof should be False"
    #     generated_proof_data = prepare_generated_proof(args.generated_proof_path)
    prompts_type = args.prompts_type


    # -- load meta data
    with open(args.aligned_path) as f:
        metadata = json.load(f)
    
    name_to_info = {}
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
    args.name_to_info=name_to_info
    print(f" > Number of metadata:", len(name_to_info))

    temperature_schedule = [args.temperature] * args.n_attempts

    generated_json_path = f"{args.dump_path}.json"
    print("Generated json path:", generated_json_path)
    if os.path.exists(generated_json_path):
        with open(generated_json_path) as f:
            generated_data = json.load(f)
        num_generated = {}
        for problem_id, generated in generated_data.items():
            num_generated[problem_id] = len(generated)

    # make_print_to_file(os.path.join(dump_path,"log.txt"))
    parameters = []
    problem_names = get_problem_names(split=args.split)
    # problem_names=["mathd_numbertheory_66"]
    problem_names_finish=get_finish(args,args.begin_success!=0)
    for problem_name, info in name_to_info.items():
        if (problem_name in problem_names) and (not problem_name in  problem_names_finish):
            parameters.append(problem_name)
    
    # arg.chunk_size attempts per array job
    all_sub_lists = []
    args_list=[]
    parallel_process = 2
    problem_ranks = [idx for idx in range(len(parameters))]
    problem_ranks_list=[]
    count=args.start_rank
    random.Random(42).shuffle(parameters)
    print(parameters)

    args.fileToFinish=os.path.join(args.dump_path,args.fileToFinish)

    #For Lock & UnLock Indicator
    with open(args.fileToFinish,"wb") as f:
        pickle.dump(parameters,f)
    #For Store to-finish files
    with open(args.fileToFinish.replace(".txt", ""),"wb") as f:
        pickle.dump(parameters,f)
    # args[0].fileToFinish

    # for i in range(0, len(parameters), args.chunk_size):
    #     size_this=min(i + args.chunk_size,len(parameters))-i
    #     sub_list = parameters[i:i+size_this]
    #     all_sub_lists.append(sub_list)
    #     args_list.append([args]*size_this)
    #     problem_ranks_list.append([count]*size_this)
    #     count=count+1
    print(f"Number of cases in total: {len(parameters)}")
    # print(f"Number of process in total: {len(all_sub_lists)}")
    # print(f"Number of chunks per process: {len(all_sub_lists[0])}")
    #
    # print(all_sub_lists)
    # print(problem_ranks_list)


    # # -- start process
    # parallel_process = 2
    # executor = submitit.LocalExecutor(folder=args.log_path)
    # executor.update_parameters(
    #     tasks_per_node=1,
    #     slurm_array_parallelism=parallel_process,
    #     # array_parallelism=parallel_process,
    #     mem_gb=4,
    #     cpus_per_task=parallel_process,
    #     timeout_min=100 * args.chunk_size * args.n_attempts,
    #     slurm_partition="Theorem_Proving,learnaccel",
    #     gpus_per_node=0,
    # )
    #
    # if not os.path.exists(os.path.join(args.dump_path, "continue.txt")):
    #     os.system(f'echo "AAA" > {os.path.join(args.dump_path, "continue.txt")}')
    #
    # os.makedirs(os.path.join(args.dump_path, "success"), exist_ok=True)
    # problem_ranks = [idx % parallel_process for idx in range(len(all_sub_lists))]
    # executor.map_array(
    #     a_single_problem_interact,
    #     problem_ranks,
    #     all_sub_lists,
    #     [args]*len(all_sub_lists)
    # )
    # # a_single_problem_interact(problem_rank=problem_ranks[0], problem_name=all_sub_lists[0], args=args)

    # -- start process

    executor = submitit.LocalExecutor(folder=args.log_path)
    executor.update_parameters(
        # tasks_per_node=1,
        slurm_array_parallelism=parallel_process,
        # array_parallelism=parallel_process,
        # mem_gb=40,
        cpus_per_task=parallel_process,
        timeout_min=3000 * args.chunk_size * args.n_attempts,
        slurm_partition="Theorem_Proving,learnaccel",
        gpus_per_node=0,
    )

    if not os.path.exists(os.path.join(args.dump_path, "continue.txt")):
        with open(os.path.join(args.dump_path, "continue.txt"),"w") as f:
            f.write(str(args))
            f.close()

    os.makedirs(os.path.join(args.dump_path, "success"), exist_ok=True)
    os.makedirs(os.path.join(args.dump_path, "failure"), exist_ok=True)

    for process_index in range(args.process_size):
        problem_ranks_list.append([count+process_index])
        args_list.append([args])
    print(problem_ranks_list)

    executor.map_array(
        a_list_problem_interact,
        problem_ranks_list,
        # all_sub_lists,
        args_list
    )
    # a_single_problem_interact(problem_rank=problem_ranks[0], problem_name=all_sub_lists[0], args=args)


    # # -- start process
    # parallel_process = 2
    # pool = Pool(processes=parallel_process)
    # if not os.path.exists(os.path.join(args.dump_path, "continue.txt")):
    #     os.system(f'echo "AAA" > {os.path.join(args.dump_path, "continue.txt")}')
    #
    # os.makedirs(os.path.join(args.dump_path, "success"), exist_ok=True)
    # problem_ranks = [idx % parallel_process for idx in range(len(all_sub_lists))]
    # # print(list(zip(problem_ranks,all_sub_lists,[args]*len(all_sub_lists)))[0])
    # pool.starmap(
    #     a_single_problem_interact,
    #     zip(problem_ranks,all_sub_lists,[args]*len(all_sub_lists))
    # )
    # # a_single_problem_interact(problem_rank=problem_ranks[0], problem_name=all_sub_lists[0], args=args)


