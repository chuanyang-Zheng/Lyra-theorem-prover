import logging
import os
ROOTDIR = os.path.abspath(os.path.join(__file__, os.path.pardir, os.path.pardir, os.path.pardir))

def setup_log(filename, name):
    logger = logging.getLogger(name)   # > set up a new name for a new logger
    logger.propagate = False
    logger.setLevel(logging.DEBUG)  # here is the missing line

    log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    log_handler = logging.FileHandler(filename, mode='w')
    log_handler.setLevel(logging.DEBUG)
    log_handler.setFormatter(log_format)

    logger.addHandler(log_handler)

    return logger

def get_isa_state(lines, problem_name):
    begin_id = end_id = None
    line_id = 0
    while line_id < len(lines):
        line = lines[line_id]
        if f"theorem {problem_name}" in line:
            begin_id = line_id
        elif "shows" in line:
            num_cite = line.count('"')
            while num_cite % 2 == 1:
                line_id += 1
                line = lines[line_id]
                num_cite += line.count('"')
            # assert 'sorry' in next_line or "proof" in next_line, "".join(lines)
            end_id = line_id
            break
        line_id += 1
    if end_id is None:
        line_id = begin_id + 1
        line = lines[line_id]
        num_cite = line.count('"')
        while num_cite % 2 == 1:
            line_id += 1
            line = lines[line_id]
            num_cite += line.count('"')
        end_id = line_id
    return "".join(lines[begin_id:end_id+1]), "".join(lines[:begin_id])

def process_isa_line(line):
    line = line.replace("\n", " ")
    line = line.replace("\\", "\\\\")
    line = line.replace('"', '\\"')
    return line

def convert_parse_to_tactics(parsed, problem_id):
    tactic_flag = False
    split_parsed = parsed.split("<SEP>")
    tactic_list = []
    if "(*statement end*)" in parsed:
        for idx, tactic in enumerate(split_parsed):
            if tactic_flag:
                tactic_list.append(process_isa_line(tactic).strip())
            elif "(*statement end*)" in tactic:
                tactic_flag = True
        return tactic_list
    else:
        for idx, tactic in enumerate(split_parsed):
            if tactic_flag:
                tactic_list.append(process_isa_line(tactic).strip())
            else:
                if f"theorem {problem_id}" in tactic:
                    tactic_flag = True
        return tactic_list

ORIGINAL_DIR = os.path.join(ROOTDIR, "draft_data/isabelle")
ORIGINAL_FILE_DICT = {} # problem_name: original_isabelle_file_path
for _split in ['test', 'valid']:
    split_dir = os.path.join(ORIGINAL_DIR, _split)
    problem_list = os.listdir(split_dir)
    for problem in problem_list:
        ORIGINAL_FILE_DICT[problem] = os.path.join(split_dir, problem)