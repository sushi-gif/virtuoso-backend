# Use an official Python runtime as the base image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set environment variables
ENV FRONTEND_URL=${FRONTEND_URL}
ENV BACKEND_URL=${BACKEND_URL}
ENV DATABASE_URL=${DATABASE_URL}
ENV KUBERNETES_API_URL=${KUBERNETES_API_URL}
ENV KUBERNATES_WS_URL=${KUBERNATES_WS_URL}
ENV KUBERNETES_TOKEN=${KUBERNETES_TOKEN}
ENV DEFAULT_NODE=${DEFAULT_NODE}
ENV NAMESPACE=${NAMESPACE}
ENV INTERFACE=${INTERFACE}
ENV BRIDGE=${BRIDGE}
ENV DEFAULT_ADMIN=${DEFAULT_ADMIN}
ENV DEFAULT_ADMIN_PWD=${DEFAULT_ADMIN_PWD}
ENV CLAUDE_KEY=${CLAUDE_KEY}
ENV SECRET_KEY=${SECRET_KEY}
ENV ALGORITHM=${ALGORITHM}
ENV ACCESS_TOKEN_EXPIRE_MINUTES=${ACCESS_TOKEN_EXPIRE_MINUTES}

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]