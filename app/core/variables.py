import os

FRONTEND_URL = os.environ['FRONTEND_URL']
BACKEND_URL = os.environ['BACKEND_URL']
DATABASE_URL = os.environ['DATABASE_URL']

KUBERNETES_API_URL = os.environ['KUBERNETES_API_URL']
KUBERNATES_WS_URL = os.environ['KUBERNATES_WS_URL']
HEADERS = {
    "Authorization": f"Bearer {os.environ['KUBERNETES_TOKEN']}"
}

DEFAULT_NODE = os.environ['DEFAULT_NODE']

NAMESPACE = os.environ['NAMESPACE']
INTERFACE = os.environ['INTERFACE']
BRIDGE = os.environ['BRIDGE']

DEFAULT_ADMIN = os.environ['DEFAULT_ADMIN']
DEFAULT_ADMIN_PWD = os.environ['DEFAULT_ADMIN_PWD']

CLAUDE_KEY = os.environ['CLAUDE_KEY']

SECRET_KEY = os.environ['SECRET_KEY']
ALGORITHM = os.environ['ALGORITHM']
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ['ACCESS_TOKEN_EXPIRE_MINUTES'])