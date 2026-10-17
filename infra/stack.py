import os
import shutil
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
    "TEXT_MODEL_ID", "ONCALL_PHONE", "REQUIRE_SPOKEN_CONFIRM",
    "CONNECT_INSTANCE_ID", "CONNECT_CONTACT_FLOW_ID", "CONNECT_SOURCE_PHONE", "CONNECT_QUEUE_ID",
]


def build_asset(service: str) -> str:
    """Package services/<service> + the shared pilotlight package into one asset directory."""
    out = ROOT / "build" / service
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(ROOT / "services" / service, out)
    shutil.copytree(ROOT / "pilotlight", out / "pilotlight",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
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

        def service_fn(cid: str, service: str, **kwargs) -> lambda_.Function:
            name = f"pilotlight-{service}"
            fn = lambda_.Function(self, cid, function_name=name,
                runtime=lambda_.Runtime.PYTHON_3_12, handler="handler.handler",
                code=lambda_.Code.from_asset(build_asset(service)), environment=env,
                log_group=logs.LogGroup(self, f"{cid}Logs", log_group_name=f"/aws/lambda/{name}",
                    retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY),
                **kwargs)
            timeline.grant_read_write_data(fn)
            incidents.grant_read_write_data(fn)
            return fn

        def grant_aws_tools(fn: lambda_.Function) -> None:
            fn.add_to_role_policy(iam.PolicyStatement(
                actions=["logs:StartQuery"], resources=[checkout_logs.log_group_arn]))
            fn.add_to_role_policy(iam.PolicyStatement(
                actions=["logs:GetQueryResults", "cloudtrail:LookupEvents"], resources=["*"]))
            fn.add_to_role_policy(iam.PolicyStatement(  # only the fail_mode parameter is writable
                actions=["ssm:GetParameter", "ssm:GetParameterHistory", "ssm:PutParameter"],
                resources=[fail_mode.parameter_arn]))
            fn.add_to_role_policy(iam.PolicyStatement(
                actions=["bedrock:InvokeModel"], resources=["*"]))

        # Amazon Connect instance scope. Wildcard until CONNECT_INSTANCE_ID is set in .env.
        instance_id = os.getenv("CONNECT_INSTANCE_ID")
        instance_arn = (f"arn:aws:connect:{self.region}:{self.account}:instance/{instance_id}"
                        if instance_id else None)
        contact_resources = [f"{instance_arn}/contact/*"] if instance_arn else ["*"]
        connect_session = [
            iam.PolicyStatement(actions=["connect:DescribeContact"], resources=contact_resources),
            iam.PolicyStatement(actions=["wisdom:ListMessages", "wisdom:UpdateSessionData"], resources=["*"]),
        ]

        incident = service_fn("Incident", "incident", timeout=Duration.seconds(60), memory_size=512,
            retry_attempts=0)  # a retry would place a second phone call
        grant_aws_tools(incident)
        incident.add_to_role_policy(iam.PolicyStatement(
            actions=["connect:StartOutboundVoiceContact"],
            resources=[f"{instance_arn}/*"] if instance_arn else ["*"]))

        # Agent tools, invoked by the AgentCore Gateway that the Connect AI agent calls over MCP.
        # The gateway enforces a 30s limit per tool call.
        tools_fn = service_fn("Tools", "tools", timeout=Duration.seconds(25), memory_size=512,
            retry_attempts=0)  # a retry could repeat a remediation
        grant_aws_tools(tools_fn)
        for st in connect_session:
            tools_fn.add_to_role_policy(st)
        gateway_role = iam.Role(self, "GatewayRole", role_name="pilotlight-gateway",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        tools_fn.grant_invoke(gateway_role)

        # Called from the contact flow to load incident context into the AI agent session
        session = service_fn("Session", "session", timeout=Duration.seconds(8))
        for st in connect_session:
            session.add_to_role_policy(st)
        session.add_permission("ConnectInvoke", principal=iam.ServicePrincipal("connect.amazonaws.com"),
            source_account=self.account, **({"source_arn": instance_arn} if instance_arn else {}))

        # Transcript to timeline and incident close when the call ends
        hangup = service_fn("Hangup", "hangup", timeout=Duration.seconds(30))
        for st in connect_session:
            hangup.add_to_role_policy(st)
        events.Rule(self, "HangupRule", rule_name="pilotlight-call-ended",
            event_pattern=events.EventPattern(
                source=["aws.connect"], detail_type=["Amazon Connect Contact Event"],
                detail={"eventType": ["DISCONNECTED"], "channel": ["VOICE"],
                        **({"instanceArn": [instance_arn]} if instance_arn else {})}),
            targets=[targets.LambdaFunction(hangup, retry_attempts=2)])

        events.Rule(self, "AlarmRule", rule_name="pilotlight-alarm-to-incident",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={"alarmName": [ALARM_NAME], "state": {"value": ["ALARM"]}}),
            targets=[targets.LambdaFunction(incident, retry_attempts=0)])

        CfnOutput(self, "ApiUrl", value=api.api_endpoint)
        CfnOutput(self, "ToolsFunctionArn", value=tools_fn.function_arn)
        CfnOutput(self, "SessionFunctionArn", value=session.function_arn)
        CfnOutput(self, "GatewayRoleArn", value=gateway_role.role_arn)
        CfnOutput(self, "DashboardUrl", value=
            f"https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/PilotLight")
