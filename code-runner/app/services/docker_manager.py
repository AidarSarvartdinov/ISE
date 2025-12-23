import docker
import tempfile
import os
import json
import logging
import time

logger = logging.getLogger(__name__)
client = docker.from_env()

def run_code_in_docker(user_code: str, config: dict):
    """
    Runs the code in the container and returns a dictionary with the results.
    Ensures that the container is removed.
    """
    container = None
    temp_dir = None
    temp_dir_obj = None
    try:
        temp_dir_obj = tempfile.TemporaryDirectory()
        temp_dir = temp_dir_obj.name

        # load the user's code
        host_file_path = os.path.join(temp_dir, "student_solution.py")
        with open(host_file_path, "w", encoding="utf-8") as f:
            f.write(user_code)
        
        # load the config
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        
        mem_limit = "256m"
        pids_limit = 20
        cpu_quota = 50_000

        container = client.containers.run(
            image="my-ds-runner:latest",
            command=["python", "/app/inspector.py", "/exchange/student_solution.py", "/exchange/config.json"],
            volumes={
                temp_dir: {'bind': '/exchange', 'mode': 'ro'}
            },
            mem_limit=mem_limit,
            pids_limit=pids_limit,
            cpu_quota=cpu_quota,
            network_disabled=True,
            detach=True,
            user="student",
            read_only=True,
            cap_drop=["ALL"],
            tmpfs={'/tmp': 'size=10m,noexec,nosuid'}
        )

        try:
            result = container.wait(timeout=8)
        except Exception:
            container.kill()
            return {"success": False, "error": "Docker Container Timeout"}
        
        logs = container.logs().decode("utf-8", errors="replace")

        try:
            return json.loads(logs)
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "Internal Error: Invalid JSON output",
                "raw_logs": logs[:1000]
            }
    except Exception as e:
        logger.error(f"Docker execution failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        # Cleaning
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if temp_dir_obj:
            try:
                temp_dir_obj.cleanup()
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")
        
