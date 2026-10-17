#!/usr/bin/env python3
"""Create Box metadata templates for Pilot Light auto-fix.

Run once:
    python scripts/box_setup_metadata.py
"""

import sys

from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.managers.metadata_templates import (
    CreateMetadataTemplateFields,
    CreateMetadataTemplateFieldsTypeField,
    CreateMetadataTemplateFieldsOptionsField,
)

# Adjust path so we can import from project root
sys.path.insert(0, ".")

from pilotlight.auto_fix.box_helpers import get_client  # noqa: E402
from pilotlight.config import BOX_ENTERPRISE_ID  # noqa: E402


def _enum_options(values: list[str]) -> list[CreateMetadataTemplateFieldsOptionsField]:
    """Build a list of Box enum option objects."""
    return [CreateMetadataTemplateFieldsOptionsField(key=v) for v in values]


def _string_field(key: str) -> CreateMetadataTemplateFields:
    return CreateMetadataTemplateFields(
        key=key,
        display_name=key,
        type=CreateMetadataTemplateFieldsTypeField.STRING,
    )


def _float_field(key: str) -> CreateMetadataTemplateFields:
    return CreateMetadataTemplateFields(
        key=key,
        display_name=key,
        type=CreateMetadataTemplateFieldsTypeField.FLOAT,
    )


def _enum_field(
    key: str, options: list[str]
) -> CreateMetadataTemplateFields:
    return CreateMetadataTemplateFields(
        key=key,
        display_name=key,
        type=CreateMetadataTemplateFieldsTypeField.ENUM,
        options=_enum_options(options),
    )


AUTO_FIX_TASK_FIELDS: list[CreateMetadataTemplateFields] = [
    _string_field("incident_id"),
    _string_field("task_id"),
    _enum_field(
        "status",
        [
            "extracted",
            "dispatched",
            "in_progress",
            "tested",
            "test_failed",
            "pr_created",
            "build_failed",
            "failed",
        ],
    ),
    _enum_field("priority", ["P1", "P2"]),
    _enum_field("task_type", ["code_fix", "config_fix", "test_addition"]),
    _string_field("pr_url"),
    _string_field("alarm_name"),
    _float_field("confidence_score"),
]

INCIDENT_FIELDS: list[CreateMetadataTemplateFields] = [
    _string_field("incident_id"),
    _string_field("alarm_name"),
    _string_field("service"),
    _enum_field(
        "status",
        ["open", "resolved", "auto_fix_in_progress", "auto_fix_complete"],
    ),
    _float_field("auto_fix_pr_count"),
]


def create_template(
    client,
    display_name: str,
    template_key: str,
    fields: list[CreateMetadataTemplateFields],
) -> None:
    """Create a metadata template, ignoring 409 (already exists)."""
    try:
        template = client.metadata_templates.create_metadata_template(
            scope="enterprise",
            display_name=display_name,
            template_key=template_key,
            fields=fields,
        )
        print(f"Created template: {template.template_key} (id={template.id})")
    except BoxAPIError as err:
        if err.response_info and err.response_info.status_code == 409:
            print(f"Template '{template_key}' already exists -- skipping.")
        else:
            raise


def main() -> None:
    client = get_client()

    print("Creating 'autoFixTask' metadata template...")
    create_template(client, "Auto Fix Task", "autoFixTask", AUTO_FIX_TASK_FIELDS)

    print("Creating 'incident' metadata template...")
    create_template(client, "Incident", "incident", INCIDENT_FIELDS)

    print("Done.")


if __name__ == "__main__":
    main()
