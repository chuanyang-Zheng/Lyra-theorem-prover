#python local_codex_query.py --dump_path dump/chuanyang_draft_all --codex_generation --omit_formal
python local_codex_query_interact.py --dump_path dump/chuanyang_sketch_all_test_gpt35turbo --model gpt-3.5-turbo-16k --n_examples 3 --n_attempts 5 --chunk_size 1
#python extract_sketch_file.py --data_name imo_d100s1