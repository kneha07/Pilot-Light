"""Box client using Client Credentials Grant (service account)."""
from box_sdk_gen import BoxCCGAuth, BoxClient, CCGConfig

from .config import BOX_CLIENT_ID, BOX_CLIENT_SECRET, BOX_ENTERPRISE_ID

_client = None


def client() -> BoxClient:
    global _client
    if _client is None:
        cfg = CCGConfig(client_id=BOX_CLIENT_ID, client_secret=BOX_CLIENT_SECRET,
                        enterprise_id=BOX_ENTERPRISE_ID)
        _client = BoxClient(auth=BoxCCGAuth(config=cfg))
    return _client
