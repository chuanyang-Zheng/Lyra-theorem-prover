from func_timeout import FunctionTimedOut
from formal_system_servers.isabelle_server_backend import IsabelleServer, IsabelleFatalError
import re
import os
from src.isa_auto.utils_auto import ROOTDIR, process_isa_line, convert_parse_to_tactics, get_isa_state
from contextlib import contextmanager
import signal
import time
import logging

logger = logging.getLogger("run_completor")

def error_message_formalize(error_message):
    output={}
    output['error']=error_message
    return output
class ProofCompletorISA:
    '''
    check and complete sledgehammer for an isabelle .thy file
    '''
    def __init__(self, isa_gym_dir, original_file_dict, rank=0, interactive_dir=None, cache_dir="/cache/",postprocess=True):
        self.isa_gym_dir = isa_gym_dir
        self.rank = rank
        self.cache_dir = cache_dir
        self.server = None
        self.original_file_dict = original_file_dict
        self.interactive_dir = os.path.join(ROOTDIR, "data/isabelle/miniF2F/interactive") if interactive_dir is None else interactive_dir
        # self.global_header = 'theory XXX imports HOL.HOL Complex_Main "HOL-Library.Code_Target_Numeral" "HOL-Library.Sum_of_Squares" "Symmetric_Polynomials.Vieta" "HOL-Computational_Algebra.Computational_Algebra" "HOL-Number_Theory.Number_Theory" \n begin\n'
        self.global_header = 'theory XXX imports HOL.HOL Complex_Main "HOL-Library.Code_Target_Numeral" "HOL-Library.Sum_of_Squares" "HOL-Computational_Algebra.Computational_Algebra" "HOL-Number_Theory.Number_Theory" \n begin\n'
        # self.global_header = 'theory XXX imports HOL.HOL Complex_Main  \n begin\n'
        heuristics = ['auto','arith','blast', 'simp',  'fastforce', 'force', 'eval', 'presburger', 'sos',
                            'linarith', '(auto simp: field_simps)']
        self.heuristics = [f"by {x}" for x in heuristics] + ['sledgehammer']
        self.problem2searchID = {}
        self.problem2init_state = {}
        self.search_ids = []
        self.postprocess=postprocess

        if postprocess:
            print("PostProcess for SCC")

    def clear_search(self):
        for search_id in self.search_ids:
            self.server.clear_search(search_id)
        self.search_ids = []
    
    def init_search(self, problem_id, sketch_file, init_from_original=False):
        problem_id_thy = problem_id


        # if init search is already completed
        if problem_id_thy in self.problem2searchID:
            print(f"[INIT SEARCH] problem already initialized...")
            output = self.problem2init_state[problem_id_thy]
            self.tactic_id = 0
            self.search_id = self.problem2searchID[problem_id_thy]
            if self.search_id is None:
                return False, error_message_formalize(f"[INIT SEARCH] problem already initialized...")
            return True, error_message_formalize(f"[INIT SEARCH] problem already initialized...")
        
        
        print(f"[INIT SEARCH] init_search {problem_id_thy}...")
        try:
            if init_from_original:
                # print(self.original_file_dict)
                original_isa_path = self.original_file_dict[problem_id_thy]
                with open(original_isa_path) as f:
                    lines = f.readlines()
            else:
                with open(sketch_file) as f:
                    lines = f.readlines()
            formal_statement, _ = get_isa_state(lines, problem_id)
            formal_statement = process_isa_line(formal_statement)
            
            # replace header
            theorem_flag = False
            new_problem_file = os.path.join(self.interactive_dir, problem_id_thy)
            with open(new_problem_file, "w") as f:
                f.write(self.global_header.replace("XXX", problem_id))
                for line in lines:
                    if theorem_flag:
                        f.write(line)
                    elif "begin" in line:
                        theorem_flag = True
            
            print("[INIT SEARCH] init...")
            print(f"[INIT SEARCH] path to file:{new_problem_file}")
            print(f"[INIT SEARCH] statement: {formal_statement}")
            output = self.server.init_search(path_to_file=new_problem_file, theorem_name=formal_statement)
            if output['error'] is not None:
                print(f"[INIT SEARCH] (should not be here!) init failed with error [{output['error']}]")
                return False,  error_message_formalize(output['error'])
        except IsabelleFatalError:
            print("[INIT SEARCH] IsabelleFatalError occurred")
            print('[INIT SEARCH] reset server...')
            self.reset_formal_system()
            self.problem2searchID[problem_id_thy] = None
            self.problem2init_state[problem_id_thy] = None
            return False, error_message_formalize("[INIT SEARCH] IsabelleFatalError occurred")
        # except:
        #     print("init search failed ...")
        #     print("you should not be here, really not so good")
        #     self.problem2searchID[problem_id_thy] = None
        #     self.problem2init_state[problem_id_thy] = None
        #     return "Init failed"
        self.tactic_id = output['tactic_state_id']
        self.search_id = output['search_id']
        self.search_ids.append(self.search_id)
        self.problem2searchID[problem_id_thy] = self.search_id
        self.problem2init_state[problem_id_thy] = output
        print(f"[INIT SEARCH] Init result: {output}")
        return True, output
    
    def parse_proof(self, problem_id, sketch_file):
        try:
            print(f"[PARSE PROOF] path_to_file: {sketch_file}")
            parse_text = self.server.parse_text(search_id=self.search_id, path_to_file=sketch_file)
            if parse_text["error"] is not None:
                print(f"[PARSE PROOF] Error with output: {parse_text}")
                return False,"No tactics", error_message_formalize(f"[PARSE PROOF] Error with output: {parse_text}")
            tactics = convert_parse_to_tactics(parse_text['tactic_state'], problem_id=problem_id)
            print(f'[PARSE PROOF] Parsed tactics: {tactics}')
            return True, tactics,error_message_formalize(f'[PARSE PROOF] Parsed tactics: {tactics}')
        except IsabelleFatalError:
            print(f"[PARSE PROOF] IsabelleFatalError: Parse failed...")
            print('[PARSE PROOF] reset server...')
            self.reset_formal_system()
            return False, "No tactics",error_message_formalize(f"[PARSE PROOF] IsabelleFatalError: Parse failed...")
    
    def proof_theorem(self, problem_id, tactics, skip_hammer):
        problem_id_thy = problem_id
        tactic_id = self.tactic_id
        before_tactics="Empty"
        output = {'error:': "Error EXCEPTION" }

        sledgehammer_ori=True
        for tactic in tactics:

            tactic_dict={"default_success":False,"sledgehammer_ori":sledgehammer_ori,"sledgehammer_success_count":False,"tc_success_count":False}
            before_tactics = tactic
            print(before_tactics)

            ###Postprocess
            if tactic == "sorry" or tactic=="oops":
                tactic = "by auto"
            tactic=tactic.replace("‹","")
            tactic = tactic.replace("›", "")
            ###Postprocess



            try:
                output = self.server.run_tac(search_id=self.search_id, tactic_id=tactic_id, tactic=tactic)
            except Exception as e:
                output = {'error (From Geneted)': "EXCEPTION:" + str(e)}

            if  (output['error'] is None):
                tactic_dict['default_success']=True

            if not (output['error'] is None):

                ###Postprocess

                if self.postprocess:
                    if tactic.strip().startswith("by") or tactic==".":
                        tactic="sledgehammer"
                    print("Before: {}\nAfter: {}\n".format(before_tactics,tactic))
                ###Postprocess

                if "sledgehammer" in tactic:
                    print("[SLEDGEHAMMER] Sledgehammer method...")
                    if skip_hammer:
                        print(f"tactic: [sorry], tactic_id: {tactic_id}, search_id: {self.search_id}")
                        try:
                            output = self.server.run_tac(search_id=self.search_id, tactic_id=tactic_id, tactic="sorry")
                        except:
                            output = {'error': 'tactic error'}
                        print(f"output: {output}")
                        print("===")
                    else:
                        print("[SLEDGEHAMMER] Trying heuristics...")
                        count_heuristic=0
                        for heuristic in self.heuristics:
                            count_heuristic+=1
                            print(f"tactic: [{heuristic}], tactic_id: {tactic_id}, search_id: {self.search_id}")
                            try:
                                output = self.server.run_tac(search_id=self.search_id, tactic_id=tactic_id, tactic=heuristic)
                            except FunctionTimedOut as e:
                                # Isabelle fatal
                                self.reset_formal_system()
                                self.problem2searchID.pop(problem_id_thy)
                                self.problem2init_state.pop(problem_id_thy)
                                output = {'error':  "EXCEPTION:" + str(e)}
                                print(f"output: {output}")
                                break
                            except Exception as e:
                                output = {'error':  "EXCEPTION:" + str(e)}
                            print(f"output: {output}")

                            if count_heuristic==3:
                                output_first=output

                            if output['error'] is None:
                                print("===")
                                break
                        if not output['error'] is None:
                            output=output_first
                else:
                    # print("tactic:", tactic, "tactic_id:", tactic_id, "search_id", search_id)
                    print(f"tactic: [{tactic}], tactic_id: {tactic_id}, search_id: {self.search_id}")
                    try:
                        output = self.server.run_tac(search_id=self.search_id, tactic_id=tactic_id, tactic=tactic)
                    except Exception as e:
                        output = {'error': str(e)}
                    time.sleep(0.1)
                    print(f"output: {output}")
                    print("===")
            output['tactic_info']=before_tactics


            if output['error'] is None:

                tactic_dict["tc_success_count"] = True
                if before_tactics.strip() != "sledgehammer" and tactic_dict['default_success']==False:
                    tactic_dict["sledgehammer_ori"] = False
                    sledgehammer_ori=False


                if before_tactics.strip() == "sledgehammer" or tactic_dict['default_success']==True:
                    tactic_dict["sledgehammer_success_count"] = True

                print(tactic_dict)





            if output['error'] is not None:

                self.server.reset_search(search_id=self.search_id)
                return "tactic_failed", output
            if output['tactic_state'] == 'no goals':

                self.server.reset_search(search_id=self.search_id)
                return "success", output
            tactic_id = output['tactic_state_id']

        
        self.server.reset_search(search_id=self.search_id)

        output['tactic_info']=before_tactics
        output['error']="proof_incomplete"
        return "proof_incomplete", output

    def complete(self, problem_id, sketch_file, skip_hammer=False, init_from_original=False):

        # init search
        print("[PROOF COMPLETOR] =====> Proof init...")
        ret, output = self.init_search(problem_id=problem_id, sketch_file=sketch_file, init_from_original=init_from_original)
        output['tactic_info']="Fail for Proof Init"
        if ret is False:
            return "init_failed",output


        # parse current sketch
        print("[PROOF COMPLETOR] =====> Parse sketch...")
        ret, tactics,output = self.parse_proof(problem_id=problem_id, sketch_file=sketch_file)
        output['tactic_info'] = "Fail for Parse Sketch"
        if ret is False:
            return "parsed_failed",output

        # start proof
        print("[PROOF COMPLETOR] =====> Proof Start...")
        ret, output = self.proof_theorem(problem_id=problem_id, tactics=tactics, skip_hammer=skip_hammer)
        
        return ret, output

    def reset_formal_system(self):
        if self.server is not None:
            try:
                self.server.clear_search(self.search_id)
            except:
                print("Function timeout on clear_search")
            self.server.kill()
        self.server = IsabelleServer(isabelle_gym_dir=self.isa_gym_dir, rank=self.rank, cache_dir=self.cache_dir)

    def kill(self):
        if self.server is not None:
            try:
                self.server.clear_search(self.search_id)
            except :
                print("Function timeout on clear_search")
            self.server.kill()
    def reset_search(self):
        try:
            self.server.reset_search(search_id=self.search_id)
        except:
            print("Fail to reset_search")
