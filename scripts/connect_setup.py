#!/usr/bin/env python3
"""Create or update the AgentCore Gateway that exposes Pilot Light tools to the Connect AI agent.

Idempotent. Run after `cdk deploy`, and again whenever connect/tool_schema.json changes.
Needs CONNECT_INSTANCE_ID and CONNECT_INSTANCE_URL in .env.
"""
import json
import os
import sys
import time
from pathlib import Path

import boto3
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

REGION = "us-east-1"
GATEWAY_NAME = "pilotlight-tools"
TARGET_NAME = "pilotlight"  # tools appear to the agent as pilotlight___<tool>
MCP_VERSION = "2025-03-26"  # the version Amazon Connect speaks

agentcore = boto3.client("bedrock-agentcore-control", region_name=REGION)
connect = boto3.client("connect", region_name=REGION)
cfn = boto3.client("cloudformation", region_name=REGION)


def stack_outputs() -> dict:
    stack = cfn.describe_stacks(StackName="PilotLight")["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def wait_ready(gateway_id: str) -> dict:
    for _ in range(60):
        g = agentcore.get_gateway(gatewayIdentifier=gateway_id)
        if g["status"] == "READY":
            return g
        if g["status"] == "FAILED":
            sys.exit(f"gateway failed: {g.get('statusReasons')}")
        time.sleep(3)
    sys.exit("gateway did not become READY")


def find_gateway() -> str | None:
    kwargs = {}
    while True:
        r = agentcore.list_gateways(**kwargs)
        for g in r["items"]:
            if g["name"] == GATEWAY_NAME:
                return g["gatewayId"]
        if not r.get("nextToken"):
            return None
        kwargs["nextToken"] = r["nextToken"]


def ensure_gateway(role_arn: str, discovery_url: str) -> dict:
    gateway_id = find_gateway()
    if not gateway_id:
        gateway_id = agentcore.create_gateway(
            name=GATEWAY_NAME, roleArn=role_arn, protocolType="MCP",
            protocolConfiguration={"mcp": {"supportedVersions": [MCP_VERSION]}},
            authorizerType="CUSTOM_JWT",
            authorizerConfiguration={"customJWTAuthorizer": {
                "discoveryUrl": discovery_url, "allowedAudience": ["pending"]}},
            description="Pilot Light incident tools for the Amazon Connect AI agent")["gatewayId"]
        print(f"created gateway {gateway_id}")
    wait_ready(gateway_id)
    # Connect sends a JWT whose aud claim is the gateway ID, which only exists after creation
    agentcore.update_gateway(
        gatewayIdentifier=gateway_id, name=GATEWAY_NAME, roleArn=role_arn, protocolType="MCP",
        protocolConfiguration={"mcp": {"supportedVersions": [MCP_VERSION]}},
        authorizerType="CUSTOM_JWT",
        authorizerConfiguration={"customJWTAuthorizer": {
            "discoveryUrl": discovery_url, "allowedAudience": [gateway_id]}},
        description="Pilot Light incident tools for the Amazon Connect AI agent")
    return wait_ready(gateway_id)


def ensure_target(gateway_id: str, tools_arn: str) -> None:
    schema = json.loads((ROOT / "connect" / "tool_schema.json").read_text())
    config = {"mcp": {"lambda": {"lambdaArn": tools_arn, "toolSchema": {"inlinePayload": schema}}}}
    creds = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
    targets = agentcore.list_gateway_targets(gatewayIdentifier=gateway_id)["items"]
    existing = next((t for t in targets if t["name"] == TARGET_NAME), None)
    if existing:
        agentcore.update_gateway_target(gatewayIdentifier=gateway_id, targetId=existing["targetId"],
            name=TARGET_NAME, targetConfiguration=config, credentialProviderConfigurations=creds)
        print(f"updated target {TARGET_NAME} ({len(schema)} tools)")
    else:
        agentcore.create_gateway_target(gatewayIdentifier=gateway_id, name=TARGET_NAME,
            targetConfiguration=config, credentialProviderConfigurations=creds)
        print(f"created target {TARGET_NAME} ({len(schema)} tools)")


def associate_session_lambda(instance_id: str, fn_arn: str) -> None:
    try:
        connect.associate_lambda_function(InstanceId=instance_id, FunctionArn=fn_arn)
        print("associated pilotlight-session with the Connect instance")
    except connect.exceptions.ResourceConflictException:
        print("pilotlight-session already associated with the Connect instance")


def main() -> None:
    instance_id = os.getenv("CONNECT_INSTANCE_ID")
    instance_url = os.getenv("CONNECT_INSTANCE_URL", "").rstrip("/")
    if not instance_id or not instance_url:
        sys.exit("Set CONNECT_INSTANCE_ID and CONNECT_INSTANCE_URL in .env first")
    out = stack_outputs()
    missing = [k for k in ("ToolsFunctionArn", "SessionFunctionArn", "GatewayRoleArn") if k not in out]
    if missing:
        sys.exit(f"Stack outputs missing {missing}. Run cdk deploy first.")

    gateway = ensure_gateway(out["GatewayRoleArn"], f"{instance_url}/.well-known/openid-configuration")
    ensure_target(gateway["gatewayId"], out["ToolsFunctionArn"])
    associate_session_lambda(instance_id, out["SessionFunctionArn"])
    print(f"\nGateway {GATEWAY_NAME}: {gateway['gatewayId']}\n  {gateway['gatewayUrl']}")
    print("Next: finish the console steps in connect/SETUP.md (MCP integration, AI agent, bot, flow).")


if __name__ == "__main__":
    main()
