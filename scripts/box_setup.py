"""One-time Box setup: folders, runbook metadata template, runbook upload, collaborators.

Usage: python scripts/box_setup.py teammate1@example.com teammate2@example.com
Prints BOX_RUNBOOKS_FOLDER_ID and BOX_INCIDENTS_FOLDER_ID for .env and the Lambda env.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from box_sdk_gen import (CreateCollaborationAccessibleBy,
                         CreateCollaborationAccessibleByTypeField,
                         CreateCollaborationItem, CreateCollaborationItemTypeField,
                         CreateCollaborationRole, CreateFolderParent,
                         CreateFileMetadataByIdScope, UploadFileAttributes,
                         UploadFileAttributesParentField)
from box_sdk_gen.box.errors import BoxAPIError

from pilotlight.box_client import client
from pilotlight.config import BOX_ENTERPRISE_ID

RUNBOOK = pathlib.Path(__file__).resolve().parent.parent / "runbooks" / "checkout-5xx.md"


def folder(name: str) -> str:
    try:
        return client().folders.create_folder(name, CreateFolderParent(id="0")).id
    except BoxAPIError as e:
        if e.response_info.status_code != 409:
            raise
        return str(e.response_info.body["context_info"]["conflicts"][0]["id"])


def ensure_template() -> None:
    from box_sdk_gen import CreateMetadataTemplateFields as F
    from box_sdk_gen import CreateMetadataTemplateFieldsOptionsField as O
    from box_sdk_gen import CreateMetadataTemplateFieldsTypeField as T
    try:
        client().metadata_templates.create_metadata_template(
            "enterprise", "runbook", template_key="runbook", fields=[
                F(type=T.STRING, key="service", display_name="service"),
                F(type=T.STRING, key="alarm_name", display_name="alarm_name"),
                F(type=T.ENUM, key="severity", display_name="severity",
                  options=[O(key="sev1"), O(key="sev2"), O(key="sev3")]),
            ])
        print("Created metadata template 'runbook'")
    except BoxAPIError as e:
        print(f"Template not created ({e.response_info.status_code}); create it in the Admin Console if missing.")


def upload_runbook(runbooks_id: str) -> None:
    try:
        f = client().uploads.upload_file(
            UploadFileAttributes(name=RUNBOOK.name, parent=UploadFileAttributesParentField(id=runbooks_id)),
            RUNBOOK.open("rb")).entries[0]
        print(f"Uploaded {RUNBOOK.name}: {f.id}")
    except BoxAPIError as e:
        if e.response_info.status_code != 409:
            raise
        f_id = e.response_info.body["context_info"]["conflicts"]["id"]
        print(f"{RUNBOOK.name} already exists: {f_id}")
        f = client().files.get_file_by_id(f_id)
    try:
        client().file_metadata.create_file_metadata_by_id(
            f.id, CreateFileMetadataByIdScope.ENTERPRISE, "runbook",
            {"service": "checkout-api", "alarm_name": "pilotlight-checkout-5xx", "severity": "sev2"})
        print("Applied runbook metadata")
    except BoxAPIError as e:
        print(f"Metadata not applied ({e.response_info.status_code}): may already exist or template missing")


def collaborate(folder_id: str, login: str) -> None:
    try:
        client().user_collaborations.create_collaboration(
            CreateCollaborationItem(type=CreateCollaborationItemTypeField.FOLDER, id=folder_id),
            CreateCollaborationAccessibleBy(type=CreateCollaborationAccessibleByTypeField.USER, login=login),
            CreateCollaborationRole.EDITOR)
        print(f"Added {login} to folder {folder_id}")
    except BoxAPIError as e:
        print(f"Could not add {login} to {folder_id}: {e.response_info.status_code}")


if __name__ == "__main__":
    runbooks, incidents = folder("Runbooks"), folder("Incidents")
    ensure_template()
    upload_runbook(runbooks)
    for login in sys.argv[1:]:
        for fid in (runbooks, incidents):
            collaborate(fid, login)
    print(f"\nBOX_RUNBOOKS_FOLDER_ID={runbooks}\nBOX_INCIDENTS_FOLDER_ID={incidents}")
