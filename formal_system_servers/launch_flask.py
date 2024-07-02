from flask import Flask
from flask import request
import argparse
from lean_server_backend import LeanServer, LeanFatalErrorServer
from isabelle_server_backend import IsabelleServer, IsabelleFatalError
from mm_server_backend import MMServer
import sys
import operator
import json
from func_timeout import FunctionTimedOut
app = Flask(__name__)

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


@app.route('/run_cmd')
def run_cmd():
    cmd = request.args.get('cmd')
    if cmd == 'TEST_CONNECTION':
        return 'SUCCESS'
    if cmd == "reset_server":
        app.logger.info("Reset formal system server.")
        global formal_system_server
        global args
        operator.methodcaller('kill')(formal_system_server)
        del formal_system_server
        if args.formal_system == 'lean':
            formal_system_server = LeanServer('lean', lean_gym_dir=args.lean_gym_dir)
        elif args.formal_system == 'isabelle':
            formal_system_server = IsabelleServer(isabelle_gym_dir=args.isabelle_gym_dir,
                                                  rank=args.port - args.base_port)
        elif args.formal_system == 'metamath':
            formal_system_server = MMServer(None, None, db_file=args.metamath_db_file)
        return "Reset done."

    cmd_args = request.args.get('args')
    # app.logger.debug("str_cmd_args: " + cmd_args)
    cmd_args = json.loads(cmd_args)
    # app.logger.info("CMD:")
    # app.logger.info(cmd)
    # app.logger.info("Args: ")
    # app.logger.info(cmd_args)
    try:
        res = str(operator.methodcaller(cmd, *cmd_args)(formal_system_server))
    except (LeanFatalErrorServer, IsabelleFatalError, FunctionTimedOut):
        res = "FormalSystemFatalError"
    #     app.logger.info("FormalSystemFatalError occurred.")
    # app.logger.info("Response from this request:")
    # app.logger.info(res)
    sys.stdout.flush()
    return res


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--base_port", type=int, default=8000)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--formal_system", type=str, default="lean")
    parser.add_argument("--lean_gym_dir", type=str, default="lean_gym")
    parser.add_argument("--isabelle_gym_dir", type=str, default="isabelle_gym")
    parser.add_argument("--metamath_db_file", type=str, default="")

    args = parser.parse_args()
    if args.formal_system == 'lean':
        formal_system_server = LeanServer('lean', lean_gym_dir=args.lean_gym_dir)
    elif args.formal_system == 'isabelle':
        formal_system_server = IsabelleServer(isabelle_gym_dir=args.isabelle_gym_dir,
                                              rank=args.port - args.base_port)
    elif args.formal_system == 'metamath':
        formal_system_server = MMServer(None, None, db_file=args.metamath_db_file)
    else:
        raise NotImplementedError()

    app.run(port=args.port, debug=True, host="0.0.0.0", use_reloader=False, threaded=False, processes=1)
