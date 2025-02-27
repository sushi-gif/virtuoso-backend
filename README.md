# FastAPI Backend

This is a FastAPI-based backend application designed to serve as the core of your system. It provides RESTful APIs, integrates with a database, and interacts with external services.

---

## Features

- **RESTful API**: Built using FastAPI for high performance and easy-to-use endpoints.
- **Environment Variables**: All configurations are managed via environment variables for flexibility and security.
- **Database Integration**: Supports SQLite (or other databases via `DATABASE_URL`).
- **Kubernetes Integration**: Interacts with Kubernetes APIs for orchestration.
- **Authentication**: Implements JWT-based authentication for secure access.

---

## Prerequisites

Before running the application, ensure you have the following installed:

- Python 3.9 or higher
- Docker (optional, for containerized deployment)
- Git (optional, for version control)

---

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/your-repo.git
cd your-repo
```

### 2. Install Dependencies
Create a virtual environment and install the required dependencies:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set Environment Variables
Create a .env file in the root directory and add the following variables:

```bash
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
DATABASE_URL=sqlite:///./local.db
KUBERNETES_API_URL=http://192.168.0.122:8001
KUBERNATES_WS_URL=ws://192.168.0.122:8001
KUBERNETES_TOKEN=your-kubernetes-token
DEFAULT_NODE=minikube
NAMESPACE=default
INTERFACE=default
BRIDGE=br0
DEFAULT_ADMIN=admin
DEFAULT_ADMIN_PWD=admin
CLAUDE_KEY=your-claude-key
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=360
```

Replace the placeholder values with your actual configuration.

### 4. Run the Application
Start the FastAPI server using Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```


## Docker Deployment
You can also run the application using Docker for a containerized setup.

### 1. Build the Docker Image
```bash
docker build -t fastapi-app .
```

### 2. Run the Docker Container
```bash
docker run -d --env-file .env -p 8000:8000 fastapi-app
```

The application will be accessible at http://localhost:8000.

