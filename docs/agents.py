from architecture import CONFLUENCE_ICON, HERE, SLIDE, box, canvas, label, render
from diagrams import Cluster
from diagrams.aws.compute import EC2, ElasticContainerServiceTask, Fargate
from diagrams.aws.integration import Eventbridge, StepFunctions
from diagrams.aws.ml import Bedrock
from diagrams.aws.security import IAMAccessAnalyzer
from diagrams.aws.storage import S3
from diagrams.custom import Custom
from diagrams.onprem.client import User, Users
from diagrams.onprem.vcs import Github

OUTPUT = str(HERE / ("agents-slide" if SLIDE else "agents"))


def draw(pad: str) -> None:
    with canvas("KIP multi-agent interaction", OUTPUT, pad):
        with Cluster("Triggers", graph_attr=box("#f7f9fc", "#d5deea")):
            people = Users("Users")
            events = Eventbridge("EventBridge")

        with Cluster("Task control plane", graph_attr=box("#f4f0fe", "#d4c8f7")):
            service = Fargate("Task service")
            workflow = StepFunctions("Step Functions")
            approver = User("Approver")

        with Cluster(
            "Agents · read-only · never call each other",
            graph_attr=box("#eafaf5", "#a9e2cf"),
        ):
            knowledge = Bedrock("Knowledge agent")
            aws_agent = Bedrock("AWS agent")
            github_agent = Bedrock("GitHub agent")

        with Cluster("Shared evidence", graph_attr=box("#fbfcfe", "#c9d4e3")):
            kb = Bedrock("Knowledge base")
            analyzer = IAMAccessAnalyzer("Access Analyzer")
            resources = EC2("AWS resources")
            github = Github("GitHub")

        executor = ElasticContainerServiceTask("Executor task")
        audit = S3("Audit log")
        confluence = Custom("Confluence", CONFLUENCE_ICON)

        people >> label("questions · tasks") >> service
        events >> label("schedules · events", minlen="2") >> workflow
        service >> label("start") >> workflow
        approver >> label("approve") >> workflow

        service >> label("questions", minlen="2") >> knowledge
        workflow >> label("task · plan", dir="both") >> aws_agent
        workflow >> label("task · plan", dir="both") >> github_agent

        knowledge >> label("retrieve") >> kb
        aws_agent >> label("standards") >> kb
        aws_agent >> label("findings") >> analyzer
        aws_agent >> label("read") >> resources
        github_agent >> label("relationships") >> kb
        github_agent >> label("read") >> github
        kb << label("connector sync") << confluence

        workflow >> label("approved steps") >> executor
        executor >> label("change") >> resources
        executor >> label("pull request") >> github
        workflow >> label("every step") >> audit


if __name__ == "__main__":
    render(draw, OUTPUT)
