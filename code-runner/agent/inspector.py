import sys
import traceback
import multiprocessing
import importlib
import tracemalloc
import time
import builtins
import argparse
import json
from typing import TypedDict, Optional, Callable, Any
from utils import LimitedStream


# TYPES

class ForbiddenMethod(TypedDict):
    path: str  # time.sleep or pandas.DataFrame.apply
    reason: str

class CodeResult(TypedDict):
    success: bool
    output: str
    error: Optional[str]
    truncated: bool
    memory_peak_mb: Optional[float]
    execution_time: Optional[float]
    variables: Optional[dict]


# HELPERS

def create_forbidden_trigger(reason: str) -> Callable:
    """Creates a trap function that throws an error when called"""
    def _trap(*args, **kwargs):
        raise RuntimeError(f"FORBIDDEN: {reason}")
    return _trap


def resolve_target(full_path: str) -> tuple[Any, str]:
    """Gets the method and the object it belongs to from full_path"""
    parts = full_path.split('.')
    if len(parts) < 2:
        raise ValueError(f"Invalid path format: {full_path}. Expected module.object")
    
    module_name = parts[0]
    try:
        obj = importlib.import_module(module_name)
    except ImportError:
        return None, ""
    
    # go through the chain of attributes to the penultimate element
    # example: pandas.DataFrame.apply -> (DataFrame, 'apply')
    for part in parts[1:-1]:
        if not hasattr(obj, part):
            return None, "" # path not found
        obj = getattr(obj, part)
    
    target_attr_name = parts[-1]
    return obj, target_attr_name


def safe_repr(value, max_len=100):
    """Safely getting a string representation of an object"""
    try:
        t = type(value)
        if t in (int, float, bool, type(None)):
            return str(value)
        
        if t is str:
            return value[:max_len] + "..." if len(value) > max_len else value
        
        return f"<{t.__name__} object>"
    except Exception:
         return "<Error getting value>"


def serialize_variables(locals_dict: dict[str, any], max_vars=50) -> dict:
    clean_vars = {}
    count = 0

    for name, value in locals_dict.items():
        if count >= max_vars:
            break
        if name.startswith('__') or name in ['safe_import', 'builtins', 'sys']:
            continue

        clean_vars[name] = {
            "type": type(value).__name__,
            "value_preview": safe_repr(value),
            "shape": list(value.shape) if hasattr(value, 'shape') and not callable(value.shape) else None
        }
        count += 1
    return clean_vars


def safe_import(name, *args, **kwargs):
    if name in ['os', 'subprocess', 'shutil', 'sys', 'importlib', 'inspect']:
        raise ImportError(f"Security: Import of '{name}' is forbidden.")
    return __import__(name, *args, **kwargs)


# WORKER

def worker_process(user_code: str, blacklist: list[ForbiddenMethod], return_queue: multiprocessing.Queue) -> None:
    """
    executes user's code and puts the result into the queue
    """

    # Save tracing tools before patching
    _timer = time.perf_counter
    _trace_start = tracemalloc.start
    _trace_stop = tracemalloc.stop
    _trace_get = tracemalloc.get_traced_memory

    result: CodeResult = {
        "success": False,
        "output": "",
        "error": None,
        "truncated": False,
        "memory_peak_mb": 0,
        "execution_time": 0,
        "variables": {}
    }

    # Monkey Patching
    for rule in blacklist:
        target_obj, attr_name = resolve_target(rule["path"])
        if target_obj is not None and hasattr(target_obj, attr_name):
            try:
                trap = create_forbidden_trigger(rule["reason"])
                setattr(target_obj, attr_name, trap)
            except:
                # Some built-in types (str) cannot be patched in CPython.
                pass


    safe_builtins = builtins.__dict__.copy()
    safe_builtins['__import__'] = safe_import

    # remove dangerous functions from builtins 
    for dangerous in ['open', 'exec', 'eval', 'quit', 'exit']:
         if dangerous in safe_builtins:
             del safe_builtins[dangerous]

    user_globals = {'__builtins__': safe_builtins, '__name__': '__main__'}
    user_locals = {}

    # capture stdout/stderr to memory
    captured_output = LimitedStream(limit_chars=5000)
    sys.stdout = captured_output
    sys.stderr = captured_output

    _trace_start()
    start_time = _timer()
    try:
        # Compile separately to distinguish SyntaxError from Runtime Errors
        compiled_code = compile(user_code, "<student_code>", "exec")
        exec(compiled_code, user_globals, user_locals)
        result['success'] = True
        result['variables'] = serialize_variables(user_locals)
    except Exception:
        tb_list = traceback.extract_tb(sys.exc_info()[2])
        clean_tb = [frame for frame in tb_list if frame.filename == '<student_code>']
        error_msg = f"{type(sys.exc_info()[1]).__name__}: {sys.exc_info()[1]}"
        result['error'] = "".join(traceback.format_list(clean_tb)) + error_msg
    finally:
        end_time = _timer()
        _, peak = _trace_get()
        _trace_stop()

        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

        result['output'] = captured_output.getvalue()
        result["truncated"] = captured_output.truncated
        result["memory_peak_mb"] = peak/1024/1024
        result['execution_time'] = end_time - start_time

        return_queue.put(result)

    

def universal_inspector(user_code: str, blacklist: list[ForbiddenMethod], timeout_seconds=2) -> CodeResult:
    queue = multiprocessing.Queue() # contains the result of the user_code

    process = multiprocessing.Process(target=worker_process, args=(user_code, blacklist, queue))
    process.start()
    process.join(timeout=timeout_seconds)

    if process.is_alive():
        # if the process is still alive after the timeout, it is stuck.
        process.terminate() # kill (SIGTERM)
        process.join()
        return {
            "success": False,
            "error": "Time Limit Exceeded: Ваш код выполнялся слишком долго.",
            "output": "",
            "truncated": False,
            "memory_peak_mb": None,
            "execution_time": timeout_seconds,
            "variables": {}
        }
    
    # If the process has completed itself, take the result from the queue.
    if not queue.empty():
        return queue.get()
    else:
        # if the process crashed fatally (segfault)
        return {
            "success": False,
            "error": "System Error: Process crashed",
            "output": "",
            "truncated": False,
            "memory_peak_mb": None,
            "execution_time": None,
            "variables": {}
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("code_path", help="Path to the student's python file")
    parser.add_argument("config_path", help="Path to the configuration json")
    args = parser.parse_args()

    try:
        with open(args.code_path, 'r', encoding="utf-8") as f:
            user_code = f.read()
    except FileNotFoundError:
        print(json.dumps({"success": False, "error": "System Error: Code file not found"}))
        sys.exit(1)

    try:
        with open(args.config_path, 'r', encoding="utf-8") as f:
            config = json.load(f)
            blacklist = config.get("blacklist", [])
    except Exception:
        blacklist = []

    result = universal_inspector(user_code, blacklist, timeout_seconds=5)

    print(json.dumps(result, ensure_ascii=False))
