import logging

from askui import AgentExecutionStatePendingReview, AgentExecutionStateDeliveredToDestinationInput, AgentExecutionStateDeliveredToDestinationInputDeliveriesInner, AgentExecutionStatus, ScheduleRunCommand, VisionAgent  # type: ignore
from langchain_openai import AzureChatOpenAI
from pydantic import SecretStr
from vision_agent_experiments.settings import settings
import tempfile

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

chat_model = AzureChatOpenAI(
    azure_endpoint=settings.azure.openai_endpoint,
    azure_deployment=settings.azure.openai_deployment,
    api_key=SecretStr(settings.azure.openai_api_key),
    api_version=settings.azure.openai_api_version,
    model=settings.azure.openai_model,
    temperature=0.0,
)


S3_KEY_PREFIX = "workspaces/{workspace_id}/agent-executions/{agent_execution_id}/input-files/"


with VisionAgent(hub_settings=settings.hub, chat_model=chat_model) as agent:
    hub_agent_execution = agent.tools.hub.get_agent_execution(agent_execution_id=settings.execution.agent_execution_id)
    if hub_agent_execution.state.actual_instance.status == AgentExecutionStatus.CANCELED:
        logger.info("Execution was canceled")
        exit(0)
    
    if hub_agent_execution.state.actual_instance.status == AgentExecutionStatus.DELIVERED_TO_DESTINATION:
        logger.info("Execution was delivered to destination")
        exit(0)

    logger.info(f"Getting agent configuration for {settings.execution.agent_id}")
    hub_agent = agent.tools.hub.get_agent(settings.execution.agent_id)
    if hub_agent_execution.state.actual_instance.status == AgentExecutionStatus.PENDING_DATA_EXTRACTION:
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info("Downloading input files")
            agent.tools.files.download(
                local_dir_path=temp_dir,
                remote_path=S3_KEY_PREFIX.format(
                    workspace_id=settings.hub.workspace_id,
                    agent_execution_id=settings.execution.agent_execution_id,
                ),
            )
            logger.info("Loading files from disk")
            with agent.tools.files.load_files_from_disk(
                paths=[temp_dir],
                recursive=True,
            ) as files:
                logger.info("Extracting data from files")
                extracted_data = agent.tools.extractor.extract_data(
                    input_files=files,
                    data_schema=hub_agent.data_schema.model_dump(),
                )

                logger.info("Updating agent execution state")
                hub_agent_execution =agent.tools.hub.update_agent_execution(
                    agent_execution_id=settings.execution.agent_execution_id,
                    state=AgentExecutionStatePendingReview(
                        dataExtracted=extracted_data,
                    ),
                )

    if hub_agent_execution.state.actual_instance.status == AgentExecutionStatus.PENDING_REVIEW:
        logger.info("Waiting for execution status")
        hub_agent_execution = agent.tools.hub.wait_for_agent_execution_status(
            agent_execution_id=settings.execution.agent_execution_id,
            target_status={AgentExecutionStatus.CONFIRMED, AgentExecutionStatus.CANCELED},
        )
        
    if hub_agent_execution.state.actual_instance.status == AgentExecutionStatus.CANCELED:
        logger.info("Execution was canceled")
        exit(0)
            
    if hub_agent_execution.state.actual_instance.status == AgentExecutionStatus.CONFIRMED:
        logger.info("Execution was confirmed, processing data destinations")
        confirmed_data = hub_agent_execution.state.actual_instance.data_confirmed
        
        deliveries = []
        for data_destination in hub_agent.data_destinations:
            dd = data_destination.actual_instance
            if dd.type == "ASKUI_WORKFLOW":
                logger.info(f"Scheduling AskUI workflow run on host {dd.host}")
                schedule_id = agent.tools.hub.schedule_run(
                    command=ScheduleRunCommand(
                        host=dd.host,
                        workflows=dd.workflows,
                        tags=dd.runner_tags,
                        data=confirmed_data,
                    ),
                )
                deliveries.append({
                    "type": "ASKUI_WORKFLOW",
                    "schedule_id": schedule_id,
                })
            if dd.type == "WEBHOOK":
                logger.info(f"Sending webhook to {dd.url}")
                response = agent.tools.httpx.post(
                    url=dd.url,
                    headers=dd.headers,
                    json=confirmed_data,
                )
                deliveries.append({
                    "type": "WEBHOOK",
                    "response": {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": response.text,
                    },
                })

        logger.info("Updating agent execution state")
        logger.info(f"Deliveries: {deliveries}")
        agent.tools.hub.update_agent_execution(
            agent_execution_id=settings.execution.agent_execution_id,
            state=AgentExecutionStateDeliveredToDestinationInput(
                deliveries=[AgentExecutionStateDeliveredToDestinationInputDeliveriesInner(delivery) for delivery in deliveries],
            ),
        )
