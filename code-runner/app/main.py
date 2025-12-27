import logging
import os
import asyncio
import docker
from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitQueue, RabbitExchange, ExchangeType
from app.schemas import ExecutionRequest
from app.services.docker_manager import run_code_in_docker


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("faststream_worker")

RABBIT_URL = os.getenv("RABBIT_URL", "amqp://guest:guest@localhost:5672/")
AGENT_PATH = os.getenv("AGENT_PATH", "/app/agent")

broker = RabbitBroker(RABBIT_URL)
app = FastStream(broker)

jobs_queue = RabbitQueue("sandbox.jobs", durable=True)
result_exchange = RabbitExchange("sandbox.results", type=ExchangeType.DIRECT, durable=True)

@app.after_startup
async def setup_infrastructure():
    logger.info("Declaring infrastructure...")

    await broker.declare_exchange(result_exchange)
    await broker.declare_queue(jobs_queue)

    await build_agent_image()


async def build_agent_image():
    logger.info("Connecting to Docker Daemon...")
    try:
        client = docker.from_env()
        if not os.path.exists(AGENT_PATH):
            logger.error(f"Agent path not found: {AGENT_PATH}")
            return
        
        logger.info(f"Building sandbox image from {AGENT_PATH}...")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: client.images.build(
            path=AGENT_PATH,
            tag="my-ds-runner:latest",
            dockerfile="Dockerfile.agent",
            rm=True
        ))
        logger.info("Sandbox image 'my-ds-runner:latest' built successfully!")
    except Exception as e:
        logger.critical(f"Failed to build Docker image: {e}")


@broker.subscriber(jobs_queue)
async def process_job(payload: ExecutionRequest) -> None:
    logger.info(f"Received job: {payload.submission_id}")

    try:
        loop = asyncio.get_running_loop()

        # run docker
        result = await loop.run_in_executor( 
            None,
            lambda: run_code_in_docker(
                submission_id=payload.submission_id,
                user_code=payload.code,
                config=payload.config.model_dump(),
                timeout=payload.timeout
            )
        )

        # send the result to RabbitMQ
        await broker.publish(
            result.model_dump(),
            exchange=result_exchange,
            routing_key="result"
        )

        if result.success:
            logger.info(f"Finished job: {payload.submission_id}, Success: True")
        else:
            logger.error(f"Job failed: {payload.submission_id}")
            logger.error(f"Error: {result.error}")
            logger.error(f"System Error: {result.system_error}")
            logger.error(f"Output: {result.output}")

    except Exception as e:
        logger.error(f"ERROR in process_job: {e}")
