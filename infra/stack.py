import os
import shutil
import subprocess
import sys
from pathlib import Path

from aws_cdk import (
    CfnOutput, Duration, RemovalPolicy, Stack,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_cloudwatch as cw,
    aws_dynamodb as ddb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_ssm as ssm,
)
from constructs import Construct

ROOT = Path(__file__).resolve().parent.parent
FAIL_MODE_PARAM = "/pilotlight/checkout/fail_mode"
ALARM_NAME = "pilotlight-checkout-5xx"
CHECKOUT_FN = "pilotlight-checkout"

# Non-secret and hackathon-acceptable values passed from .env to the Incident Lambda.
# Production path: Box credentials in Secrets Manager.
PASSTHROUGH_ENV = [
    "BOX_CLIENT_ID", "BOX_CLIENT_SECRET", "BOX_ENTERPRISE_ID",
    "BOX_RUNBOOKS_FOLDER_ID", "BOX_INCIDENTS_FOLDER_ID", "BOX_REVIEWER_LOGIN",
    "TEXT_MODEL_ID", "ONCALL_PHONE", "VOICE_SERVER_URL",
]


def build_incident_asset() -> str:
    """Package services/incident + the shared pilotlight package into one asset directory."""
    out = ROOT / "build" / "incident"
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(ROOT / "services" / "incident", out)
    shutil.copytree(ROOT / "pilotlight", out / "pilotlight",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # box_tools imports box_sdk_gen; install Linux wheels for the Lambda runtime
    subprocess.run([sys.executable, "-m", "pip", "install", "box-sdk-gen", "-t", str(out),
                    "--platform", "manylinux2014_x86_64", "--python-version", "3.12",
                    "--only-binary=:all:", "--quiet"], check=True)
    return str(out)


class PilotLightStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Break switch
        fail_mode = ssm.StringParameter(self, "FailMode",
            parameter_name=FAIL_MODE_PARAM, string_value="off")

        # Tables
        timeline = ddb.Table(self, "Timeline", table_name="pilotlight-timeline",
            partition_key=ddb.Attribute(name="incident_id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="ts", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)
        incidents = ddb.Table(self, "Incidents", table_name="pilotlight-incidents",
            partition_key=ddb.Attribute(name="incident_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)

        # Demo checkout service
        checkout_logs = logs.LogGroup(self, "CheckoutLogs", log_group_name=f"/aws/lambda/{CHECKOUT_FN}",
            retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY)
        checkout = lambda_.Function(self, "Checkout", function_name=CHECKOUT_FN,
            runtime=lambda_.Runtime.PYTHON_3_12, handler="handler.handler",
            code=lambda_.Code.from_asset(str(ROOT / "services" / "checkout")),
            timeout=Duration.seconds(10), log_group=checkout_logs,
            environment={"FAIL_MODE_PARAM": FAIL_MODE_PARAM})
        fail_mode.grant_read(checkout)
        checkout.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"], resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "PilotLight"}}))

        api = apigw.HttpApi(self, "Api", api_name="pilotlight")
        api.add_routes(path="/checkout", methods=[apigw.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("CheckoutIntegration", checkout))

        # Fast alarm on the high-resolution error metric
        errors = cw.Metric(namespace="PilotLight", metric_name="CheckoutErrors",
            statistic="Sum", period=Duration.seconds(10))
        alarm = cw.Alarm(self, "CheckoutAlarm", alarm_name=ALARM_NAME, metric=errors,
            threshold=3, evaluation_periods=1, datapoints_to_alarm=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING)

        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name="PilotLight",
            default_interval=Duration.minutes(15))
        dashboard.add_widgets(
            cw.GraphWidget(title="Checkout errors per second", width=18, height=10,
                left=[errors.with_(period=Duration.seconds(1))],
                left_annotations=[cw.HorizontalAnnotation(value=0)]),
            cw.AlarmStatusWidget(title="Alarm", alarms=[alarm], width=6, height=10))

        # Incident Lambda
        env = {
            "FAIL_MODE_PARAM": FAIL_MODE_PARAM,
            "TIMELINE_TABLE": timeline.table_name,
            "INCIDENTS_TABLE": incidents.table_name,
            "CHECKOUT_LOG_GROUP": checkout_logs.log_group_name,
            "ALARM_NAME": ALARM_NAME,
        }
        env.update({k: os.environ[k] for k in PASSTHROUGH_ENV if os.getenv(k)})
        incident = lambda_.Function(self, "Incident", function_name="pilotlight-incident",
            runtime=lambda_.Runtime.PYTHON_3_12, handler="handler.handler",
            code=lambda_.Code.from_asset(build_incident_asset()),
            timeout=Duration.seconds(60), memory_size=512, environment=env,
            retry_attempts=0,  # a retry would place a second phone call
            log_group=logs.LogGroup(self, "IncidentLogs", log_group_name="/aws/lambda/pilotlight-incident",
                retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY))
        timeline.grant_read_write_data(incident)
        incidents.grant_read_write_data(incident)
        incident.add_to_role_policy(iam.PolicyStatement(
            actions=["logs:StartQuery"], resources=[checkout_logs.log_group_arn]))
        incident.add_to_role_policy(iam.PolicyStatement(
            actions=["logs:GetQueryResults", "cloudtrail:LookupEvents"], resources=["*"]))
        incident.add_to_role_policy(iam.PolicyStatement(  # only the fail_mode parameter is writable
            actions=["ssm:GetParameter", "ssm:GetParameterHistory", "ssm:PutParameter"],
            resources=[fail_mode.parameter_arn]))
        incident.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"], resources=["*"]))

        events.Rule(self, "AlarmRule", rule_name="pilotlight-alarm-to-incident",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={"alarmName": [ALARM_NAME], "state": {"value": ["ALARM"]}}),
            targets=[targets.LambdaFunction(incident, retry_attempts=0)])

        CfnOutput(self, "ApiUrl", value=api.api_endpoint)
        CfnOutput(self, "DashboardUrl", value=
            f"https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/PilotLight")
