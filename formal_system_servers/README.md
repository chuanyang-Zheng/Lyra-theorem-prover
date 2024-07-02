# Lean Server In Flask

## How to run
```shell
python launch_lean_flask.py --port $PORT --lean_gym_dir $LEAN_GYM_DIR
```

## How to request
```python
import requests
url = "http://127.0.0.1:%d/run_cmd" % PORT
response = requests.get(url, params={"cmd": cmd, "args": json.dumps(args)})
```
See `src/evaluation/lean_server.py` for more info.
