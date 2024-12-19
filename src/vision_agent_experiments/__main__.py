import logging

from askui import VisionAgent
from askui.tools.askui.askui_hub import (
    AgentExecutionStatePendingReview,
    AgentExecutionStateDeliveredToDestinationInput,
    ExtractDataCommand,
    ScheduleRunCommand,
)
from vision_agent_experiments.settings import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


S3_KEY_PREFIX = "workspaces/{workspace_id}/agent-executions/{agent_execution_id}/input-files/"


with VisionAgent(enable_askui_controller=False) as agent:
    logger.info(f"Getting agent execution \"{settings.askui_agent_execution_id}\"")
    hub_agent_execution = agent.tools.hub.retrieve_agent_execution(agent_execution_id=settings.askui_agent_execution_id)
    if hub_agent_execution.state.actual_instance.status == "DELIVERED_TO_DESTINATION":
        logger.info("Execution has ended (DELIVERED_TO_DESTINATION) - exiting")
        exit(0)

    logger.info(f"Getting agent \"{settings.askui_agent_id}\"")
    hub_agent = agent.tools.hub.retrieve_agent(agent_id=settings.askui_agent_id)

    if hub_agent_execution.state.actual_instance.status == "PENDING_DATA_EXTRACTION":
        logger.info("Extracting data from files")
        extract_data_response = agent.tools.hub.extract_data(
            command=ExtractDataCommand(
                filePaths=[S3_KEY_PREFIX.format(
                    workspace_id=hub_agent.workspace_id,
                    agent_execution_id=settings.askui_agent_execution_id,
                )],
                dataSchema=hub_agent.data_schema.model_dump(),
            )
        )
        logger.info("Updating agent execution state")
        hub_agent_execution =agent.tools.hub.update_agent_execution(
            agent_execution_id=settings.askui_agent_execution_id,
            state=AgentExecutionStatePendingReview(
                dataExtracted=extract_data_response.data,
            ),
        )

    if hub_agent_execution.state.actual_instance.status == "PENDING_REVIEW":
        logger.info("Waiting for review of extracted data - exiting")
        exit(0)
        
    if hub_agent_execution.state.actual_instance.status == "CANCELED":
        logger.info("Execution was canceled - exiting")
        exit(0)
            
    if hub_agent_execution.state.actual_instance.status == "CONFIRMED":
        logger.info("Execution was confirmed, processing data destinations")
        confirmed_data = hub_agent_execution.state.actual_instance.data_confirmed
        deliveries = []
        for data_destination in hub_agent.data_destinations:
            try:
                dd = data_destination.actual_instance
                if dd.type == "ASKUI_WORKFLOW":
                    logger.info("Scheduling AskUI workflow")
                    schedule = agent.tools.hub.schedule_run(
                        command=ScheduleRunCommand(
                            host=dd.host,
                            workflows=dd.workflows,
                            tags=dd.runner_tags,
                            data=confirmed_data,
                        ),
                    )
                    logger.info(f"Scheduled AskUI workflow {schedule.id}")
                    deliveries.append({
                        "type": "ASKUI_WORKFLOW",
                        "schedule_id": schedule.id,
                    })
                if dd.type == "WEBHOOK":
                    logger.info(f"Sending webhook to {dd.url}")
                    response = agent.tools.httpx.post(
                        url=dd.url,
                        headers=dd.headers,
                        json={
                            "data": confirmed_data,
                            "agent_id": str(settings.askui_agent_id),
                            "agent_execution_id": str(settings.askui_agent_execution_id),
                            "workspace_id": hub_agent.workspace_id,
                        },
                    )
                    logger.info(f"Sent webhook to {dd.url}")
                    deliveries.append({
                        "type": "WEBHOOK",
                        "response": {
                            "status_code": response.status_code,
                            "headers": dict(response.headers),
                            "body": response.text,
                        },
                    })
            except Exception as e:
                logger.error(f"Error delivering data to {dd.type}: {e}")
        logger.info("Updating agent execution state")
        agent.tools.hub.update_agent_execution(
            agent_execution_id=settings.askui_agent_execution_id,
            state=AgentExecutionStateDeliveredToDestinationInput(
                deliveries=[{"actual_instance": delivery} for delivery in deliveries],
            ),
        )
        logger.info("Execution has ended (DELIVERED_TO_DESTINATION) - exiting")
