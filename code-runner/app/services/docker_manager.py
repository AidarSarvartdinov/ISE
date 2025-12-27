import docker
import os
import json
import logging
import shutil
from app.schemas import ExecutionResult

logger = logging.getLogger(__name__)
client = docker.from_env()

EXCHANGE_DIR = os.getenv("EXCHANGE_DIR", "/exchange")
EXCHANGE_VOLUME_NAME = os.getenv("EXCHANGE_VOLUME_NAME", "code-exchange")

def run_code_in_docker(submission_id: str, user_code: str, config: dict, timeout: int) -> ExecutionResult:
    """
    Runs the code in the container and returns a dictionary with the results.
    Ensures that the container is removed.
    """
    container = None
    temp_dir = None
    try:
        # create a common volume
        temp_dir = os.path.join(EXCHANGE_DIR, f"submission_{submission_id}")
        os.makedirs(temp_dir, exist_ok=True)
        os.chmod(temp_dir, 0o777)

        # load the user's code
        host_file_path = os.path.join(temp_dir, "student_solution.py")
        with open(host_file_path, "w", encoding="utf-8") as f:
            f.write(user_code)
        os.chmod(host_file_path, 0o666)
        
        # load the config
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        os.chmod(config_path, 0o666)
        
        mem_limit = "256m"
        pids_limit = 20
        cpu_quota = 50_000

        volumes={
                EXCHANGE_VOLUME_NAME: {'bind': '/exchange', 'mode': 'ro'}
            }

        submission_subdir = f"submission_{submission_id}"
        container = client.containers.run(
            image="my-ds-runner:latest",
            command=["python", "/app/inspector.py", f"/exchange/{submission_subdir}/student_solution.py", f"/exchange/{submission_subdir}/config.json"],
            volumes=volumes,
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
            result = container.wait(timeout=timeout + 2)
        except Exception:
            container.kill()
            return ExecutionResult(
                submission_id=submission_id,
                success=False,
                output="",
                error="Docker Container Timeout"
            )
        
        logs = container.logs().decode("utf-8", errors="replace")

        try:
            data = json.loads(logs)
            data['submission_id'] = submission_id
            return ExecutionResult(**data)
        except json.JSONDecodeError:
            return ExecutionResult(
                submission_id=submission_id,
                success=False,
                output=logs[:1000],
                system_error="Invalid JSON from inspector"
            )
        
    except Exception as e:
        logger.error(f"Docker execution failed for submission {submission_id}: {e}")
        return ExecutionResult(
            submission_id=submission_id,
            success=False,
            output="",
            system_error=str(e)
        )
    finally:
        # Cleaning
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if temp_dir:
            try:
                # Remove temporary files
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir: {e}")
        
