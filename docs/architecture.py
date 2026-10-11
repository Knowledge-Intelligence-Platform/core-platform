import struct
import sys
from collections.abc import Callable
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, ElasticContainerServiceTask, Fargate
from diagrams.aws.integration import Eventbridge, StepFunctions
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import APIGateway, ElbApplicationLoadBalancer
from diagrams.aws.security import SecretsManager
from diagrams.aws.storage import S3
from diagrams.custom import Custom
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Github
from diagrams.saas.chat import Slack

HERE = Path(__file__).resolve().parent
CONFLUENCE_ICON = str(HERE / "icons" / "confluence.png")
SLIDE = "--slide" in sys.argv
OUTPUT = str(HERE / ("architecture-slide" if SLIDE else "architecture"))
FONT = "Helvetica"
INK = "#14253c"
LINE = "#5f6f86"
SLIDE_ASPECT = 16 / 9
DPI = 96


def box(fill: str, pen: str) -> dict[str, str]:
    return {
        "fontname": FONT,
        "fontsize": "15",
        "fontcolor": INK,
        "bgcolor": fill,
        "pencolor": pen,
        "style": "rounded",
        "margin": "22",
        "labeljust": "l",
    }


def label(text: str, **attrs: str) -> Edge:
    return Edge(label=f" {text} ", **attrs)


def canvas(title: str, output: str, pad: str) -> Diagram:
    return Diagram(
        "" if SLIDE else title,
        filename=output,
        outformat="png",
        show=False,
        direction="LR",
        graph_attr={
            "fontname": FONT,
            "fontsize": "26",
            "fontcolor": INK,
            "labelloc": "t",
            "pad": pad,
            "dpi": "96",
            "nodesep": "0.7",
            "ranksep": "1.2",
            "splines": "spline",
            "bgcolor": "white",
            "newrank": "true",
        },
        node_attr={"fontname": FONT, "fontsize": "14", "fontcolor": INK},
        edge_attr={
            "fontname": FONT,
            "fontsize": "12",
            "color": LINE,
            "fontcolor": "#3d4b5f",
            "penwidth": "1.4",
            "arrowsize": "0.8",
        },
    )


def draw(pad: str) -> None:
    with canvas("KIP Core Platform architecture", OUTPUT, pad):
        with Cluster("Users", graph_attr=box("#f7f9fc", "#d5deea")):
            people = Users("API users")
            slack = Slack("Slack")

        with Cluster("AWS account · us-east-1", graph_attr=box("#fbfcfe", "#c9d4e3")):
            api = APIGateway("API Gateway")
            alb = ElbApplicationLoadBalancer("Load balancer")

            with Cluster("ECS on Fargate", graph_attr=box("#fff6ea", "#f2d3a6")):
                app = Fargate("KIP app")

            with Cluster("Amazon Bedrock", graph_attr=box("#eafaf5", "#a9e2cf")):
                kb = Bedrock("Knowledge base")
                model = Bedrock("Nova Lite")

            bucket = S3("S3 bucket")

            with Cluster("Task workflow", graph_attr=box("#f4f0fe", "#d4c8f7")):
                events = Eventbridge("EventBridge")
                workflow = StepFunctions("Step Functions")
                executor = ElasticContainerServiceTask("Executor task")

            with Cluster("Operations", graph_attr=box("white", "#d5deea")):
                secrets = SecretsManager("Secrets Manager")
                image = ECR("ECR image")
                logs = Cloudwatch("CloudWatch logs")

        confluence = Custom("Confluence", CONFLUENCE_ICON)
        github = Github("GitHub")

        people >> api
        slack >> api
        api >> alb >> app

        app >> label("retrieve") >> kb
        app >> label("generate") >> model
        app >> label("tasks · audit") >> bucket
        kb << label("connector sync") << confluence

        app >> label("start · approve") >> workflow
        events >> label("schedules · events") >> workflow
        workflow >> label("approved steps") >> executor
        executor >> label("start sync") >> kb
        executor >> Edge(style="invis") >> model
        executor >> label("pull requests") >> github

        spacer = Edge(style="invis", label=" schedules · events ")
        api >> spacer >> secrets >> spacer >> image >> spacer >> logs


def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as image:
        width, height = struct.unpack(">II", image.read(24)[16:24])
    return width, height


def slide_pad(width: int, height: int, base: float) -> str:
    if width / height < SLIDE_ASPECT:
        extra = (height * SLIDE_ASPECT - width) / 2 / DPI
        return f"{base + extra:.4f},{base}"
    extra = (width / SLIDE_ASPECT - height) / 2 / DPI
    return f"{base},{base + extra:.4f}"


def render(draw_at: Callable[[str], None], output: str) -> None:
    if SLIDE:
        draw_at("0.5")
        draw_at(slide_pad(*png_size(f"{output}.png"), base=0.5))
    else:
        draw_at("0.8")


if __name__ == "__main__":
    render(draw, OUTPUT)
