import signal
import subprocess
import os
import re
from func_timeout import func_set_timeout

LEAN_PATH = os.path.expanduser('~/.elan/bin/lean')
LEAN_GYM_DIR = None


class LeanFatalErrorServer(Exception):
    """Raise when Lean fatal error ocurred"""
    pass


class LeanServer:
    def __init__(self,
                 lean_path=LEAN_PATH,
                 lean_gym_dir=LEAN_GYM_DIR,
                 normalize_tab=True):
        if lean_path == 'lean':
            lean_path = LEAN_PATH
        self.proc = subprocess.Popen([lean_path, '--run', 'src/repl.lean'],
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     cwd=lean_gym_dir)
        self.normalize_tab = normalize_tab

    @func_set_timeout(120)
    def init_search(self, dec_name, namespaces=""):
        inputs = f'["init_search", ["{dec_name}","{namespaces}"]]\n'
        return self.__run(inputs)

    @func_set_timeout(60)
    def run_tac(self, search_id, tactic_id, tactic):
        tactic = "".join(re.findall("[^\n\t\a\b\r]+",tactic))
        inputs = f'["run_tac", ["{search_id}", "{tactic_id}", "{tactic}"]]\n'
        result = self.__run(inputs)
        return result

    def clear_search(self, search_id):
        inputs = f'["clear_search",["{search_id}"]]\n'
        return self.__run(inputs)

    def __output_parse(self, output):
        null = None
        if len(output) <= 0:
            raise LeanFatalErrorServer
        output = eval(output)
        if output['search_id'] is not None:
            output['search_id'] = int(output['search_id'])
        if output['tactic_state_id'] is not None:
            output['tactic_state_id'] = int(output['tactic_state_id'])
        if self.normalize_tab:
            if output['tactic_state'] is not None:
                # assert not '\t' in output['tactic_state']
                output['tactic_state'] = output['tactic_state'].replace(
                    '\t', ' ')
        return output

    def __run(self, inputs: str):
        try:
            self.proc.stdin.write(inputs.encode())
            self.proc.stdin.flush()
        except BrokenPipeError:
            # return {'error':'broken_pipe',
            #         'search_id':None,
            #         'tactic_state':None,
            #         'tactic_state_id':None}
            print("Broken pipe")
            raise LeanFatalErrorServer
        return self.__output_parse(self.proc.stdout.readline().decode())

    def kill(self):
        # self.proc.terminate()
        os.kill(self.proc.pid, signal.SIGKILL)

if __name__=='__main__':
    leanserver = LeanServer(lean_gym_dir="../../../../lean/lean_gym")
    print(leanserver.init_search('lie_equiv.nilpotent_iff_equiv_nilpotent', 'lie_algebra lie_module'))
    print(leanserver.run_tac('0','0','intros'))
    print(leanserver.run_tac('0','1','split'))
