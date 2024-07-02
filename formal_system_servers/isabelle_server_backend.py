import datetime
import random
import psutil
import shutil
import subprocess
import os
import re
import time
from func_timeout import func_set_timeout

from contextlib import contextmanager
import signal


class IsabelleFatalError(Exception):
    """Raise when Isabell fatal error ocurred"""
    pass


class TimeoutException(Exception):
    """Raise when Isabell take too long to compute result"""
    pass

@contextmanager
def time_limit(seconds):
    def signal_handler(signum, frame):
        raise TimeoutException("Timed out!")
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)


class IsabelleServer:

    def __init__(self,
                 isabelle_gym_dir="isabelle_gym/",
                 normalize_tab=True,
                 log_out=None,
                 rank=None,
                 cache_dir="/cache/"
                 ):
        self.rank = rank
        run_dir = os.path.join(cache_dir, f"isabelle_repl_{rank}")
        if os.path.exists(run_dir):
            shutil.rmtree(run_dir)
        shutil.copytree(isabelle_gym_dir, run_dir)
        # here we assume isabelle is in home directory and heap images are in cache_dir
        isa_path = os.path.expanduser("~/Isabelle2021")
        isa_path = self.copy_isabelle_environment(isa_path=isa_path,
                                         isa_heap_images_path=os.path.join(cache_dir, "isabelle_gym/.isabelle.bak"),
                                         rank=rank,
                                         share_isa_num=2,
                                         cache_dir=cache_dir)

        self.proc = subprocess.Popen(['bash', 'run_isabelle.sh', isa_path],
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     cwd=run_dir)
        print(f"Rank {rank} Creating isabelle environment with {isa_path}")
        info = self.proc.stdout.readline().decode()
        print("info: ", info)
        self.is_alive = True
        self.has_init = False
        self.normalize_tab = normalize_tab

    @func_set_timeout(3600)
    def init_search(self, path_to_file, theorem_name="", log_out=None):
        inputs = f'["init_search", ["{path_to_file}","{theorem_name}"]]\n'
        return self.__run(inputs, log_out)

    @func_set_timeout(3600)
    def run_tac(self, search_id, tactic_id, tactic, log_out=None):
        tactic = "".join(re.findall("[^\n\t\a\b\r]+",tactic))
        inputs = f'["run_tac", ["{search_id}", "{tactic_id}", "{tactic}"]]\n'
        result = self.__run(inputs, log_out)
        return result

    def reset_search(self, search_id):
        inputs = f'["reset_search",["{search_id}"]]\n'
        return self.__run(inputs)

    def parse_text(self, search_id, path_to_file):
        inputs = f'["parse_text",["{search_id}", "{path_to_file}"]]\n'
        return self.__run(inputs)

    @func_set_timeout(3600)
    def clear_search(self, search_id):
        inputs = f'["clear_search",["{search_id}"]]\n'
        return self.__run(inputs)

    def __output_parse(self, output):
        null = None
        if '[info]' in output:
            output = output[len("[info]"):].strip()
        if len(output) <= 0:
            print("output len 0")
            raise IsabelleFatalError
        try:
            output = eval(output)
        except Exception:
            print("error line:", output)
            raise IsabelleFatalError
        if output['search_id'] is not None:
            output['search_id'] = int(output['search_id'])
        if output['tactic_state_id'] is not None and output['tactic_state_id'] != 'null':
            output['tactic_state_id'] = int(output['tactic_state_id'])
        if self.normalize_tab:
            if output['tactic_state'] is not None:
                # assert not '\t' in output['tactic_state']
                output['tactic_state'] = output['tactic_state'].replace(
                    '\t', ' ')
        return output

    def __run(self, inputs, log_out=None):
        try:
            self.proc.stdin.write(inputs.encode())
            self.proc.stdin.flush()
        except BrokenPipeError:
            print("Broken pipe")
            raise IsabelleFatalError
        # for debug:
        while True:
            line = self.proc.stdout.readline().decode()
            if not line.startswith("{"):
                # if log_out is not None:
                # with open("temp_log.txt", mode='a') as log_out:
                #     log_out.write(f"{datetime.datetime.now()} {line}")
                # if '[log]' not in line:
                # print(f"[ISABELLE GYM OUT] {line.strip()}")
                pass
            else:
                return self.__output_parse(line)

    def kill(self):
        def kill_child_processes(parent_pid, sig=signal.SIGTERM):
            try:
                parent = psutil.Process(parent_pid)
            except psutil.NoSuchProcess:
                return
            children = parent.children(recursive=True)
            for process in children:
                process.send_signal(sig)
        kill_child_processes(self.proc.pid)

    @staticmethod
    def copy_isabelle_environment(isa_path, isa_heap_images_path, rank, share_isa_num=4, cache_dir="/cache/"):
        # this index represent with process copy the environment.
        copy_index = (rank // share_isa_num) * share_isa_num
        isabelle_identifier = isa_path.split("/")[-1]

        copy_path = os.path.join(cache_dir, f"isabelle_copy_{copy_index}")
        copy_path = os.path.abspath(copy_path)
        os.makedirs(copy_path, exist_ok=True)

        # we use this file to mark that the copy have finished.
        finish_copy_marker_path = os.path.join(copy_path, "finish_marker.txt")
        main_isa_path = os.path.join(copy_path, "main_isa")
        if os.path.isfile(finish_copy_marker_path):
            return os.path.join(main_isa_path, isabelle_identifier)

        if rank != copy_index:
            print(f"Rank {rank}: waiting rank {copy_index}")
            while not os.path.isfile(finish_copy_marker_path):
                time.sleep(1)
            print(f"Rank {rank}: Finish waiting, rank {copy_index} copy completed")
            return os.path.join(main_isa_path, isabelle_identifier)

        # here we assume if the marker file existed, the copy is complete!
        print(f'Rank {rank} coping isabelle')
        if os.path.exists(os.path.join(main_isa_path, isabelle_identifier)):
            shutil.rmtree(os.path.join(main_isa_path, isabelle_identifier))
        shutil.copytree(isa_path, os.path.join(main_isa_path, isabelle_identifier), symlinks=True)

        # here we also assume if the marker file existed, the copy is complete!
        user_isa_path = os.path.join(copy_path, "user_isa")
        print(f'Rank {rank} coping heap images')
        if os.path.exists(user_isa_path):
            shutil.rmtree(user_isa_path)
        shutil.copytree(isa_heap_images_path, user_isa_path, symlinks=True)

        # Edit the settings file such that the user home points to the right directory
        original_isabelle_home_user_string = "$USER_HOME/.isabelle"
        isabelle_home_user_string = str(user_isa_path)

        isabelle_settings_path = os.path.join(main_isa_path, isabelle_identifier, "etc/settings")
        with open(isabelle_settings_path, "r") as f:
            settings = f.read()
        settings = settings.replace(original_isabelle_home_user_string, isabelle_home_user_string)
        with open(isabelle_settings_path, "w") as f:
            f.write(settings)

        # finish processing, we set the marker file
        assert os.path.exists(finish_copy_marker_path) != True
        f = open(finish_copy_marker_path, "w")
        f.close()

        return os.path.join(main_isa_path, isabelle_identifier)


# if __name__=='__main__':
#     leanserver = IsabelleServer(rank=0, cache_dir='cache/')
#     # ret = leanserver.init_search("/home/honglanqing/afp-2021-10-22/thys/Valuation/Valuation1.thy", r"lemma (in Corps) n_val_surj:\"valuation K v \\<Longrightarrow> \\<exists>x\\<in> carrier K. n_val K v x = 1\"")
#     ret = leanserver.init_search("/home/honglanqing/wanghaiming/DSP/sketch_data/output_chuanyang_sketch_all_test_gpt35turbo/test/interactive/aime_1983_p1.thy", r"theorem aime_1983_p1:   fixes x y z w :: nat   assumes ht : \"1 < x \\<and> 1 < y \\<and> 1 < z\"     and hw : \"0 \\<le> w\"     and h0 : \"ln w / ln x = 24\"     and h1 : \"ln w / ln y = 40\"     and h2 : \"ln w / ln (x * y * z) = 12\"   shows \"ln w / ln z = 60\"")
#     ret = leanserver.run_tac('0','0',r'apply (frule Lv_z[of v], erule exE, frule Lv_pos[of v], frule AMin_k[of v], erule bexE, frule_tac x = k in n_val[of v], simp, simp add:Lv_def)')
#     ret = leanserver.run_tac('0','1',r'apply (subgoal_tac \"n_val K v k * ant z = 1 * ant z\", subgoal_tac \"z \\<noteq> 0\", frule_tac z = z and a = \"n_val K v k\" and b = 1 in amult_eq_eq_r, assumption, blast, simp, simp add:amult_one_l)')
#     ret = leanserver.run_tac('0','2',r'done')
#     cnt = 0
#     while True:
#         # ret = leanserver.run_tac('0', '0', r'apply (frule Lv_z[of v], erule exE, frule Lv_pos[of v], frule AMin_k[of v], erule bexE, frule_tac x = k in n_val[of v], simp, simp add:Lv_def)')
#         # if ret['error'] == 'ACTION_TIMEOUT':
#         #     print('here')
#         # else:
#         #     print(ret['tactic_state_id'])
#         #
#         #
#         # ret = leanserver.run_tac('0', ret['tactic_state_id'], r'apply (subgoal_tac \"n_val K v k * ant z = 1 * ant z\", subgoal_tac \"z \\<noteq> 0\", frule_tac z = z and a = \"n_val K v k\" and b = 1 in amult_eq_eq_r, assumption, blast, simp, simp add:amult_one_l)')
#         # if ret['error'] == 'ACTION_TIMEOUT':
#         #     print('here')
#         # else:
#         #     print(ret['tactic_state_id'])
#         #
#         # ret = leanserver.run_tac('0', ret['tactic_state_id'], 'done')
#         # if ret['error'] == 'ACTION_TIMEOUT':
#         #     print('here')
#         # else:
#         #     print(ret['tactic_state_id'])
#         ret = leanserver.run_tac('0', '1', r'by simp')
#         if ret['error'] == 'ACTION_TIMEOUT':
#             print('here')
#         else:
#             print(cnt)
#             cnt += 1
#
#     print(ret)
#

