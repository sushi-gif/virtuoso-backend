from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.core.security import verify_token
from app.db.database import database
from app.db.models import users
from anthropic import Anthropic
from typing import Optional
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.core.variables import *

router = APIRouter()

class Message(BaseModel):
    text: str

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic(api_key=CLAUDE_KEY)
        self.current_token: Optional[str] = None

    async def connect_to_server(self, server_script_path: str):
        is_python = server_script_path.endswith('.py')
        command = "python3" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()

    async def process_query(self, query: str, token: str) -> str:
        self.current_token = token
        messages = [{"role": "user", "content": query}]
        
        response = await self.session.list_tools()
        available_tools = [{
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        } for tool in response.tools]

        # Add authentication context to tool definitions
        for tool in available_tools:
            tool["input_schema"]["properties"]["_auth_token"] = {
                "type": "string",
                "x-internal": True
            }

        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=messages,
            tools=available_tools
        )

        final_text = []
        for content in response.content:
            if content.type == 'text':
                final_text.append(content.text)
            elif content.type == 'tool_use':
                # Inject auth token into tool arguments
                tool_args = content.input or {}
                tool_args["_auth_token"] = self.current_token
                
                result = await self.session.call_tool(
                    content.name,
                    tool_args  # Now passes token within arguments
                )
                final_text.append(f"[Tool {content.name} result: {result.content}]")

        return "\n".join(final_text)

    async def cleanup(self):
        await self.exit_stack.aclose()

mcp_client = MCPClient()
SERVER_SCRIPT_PATH = "/home/sushi/Desktop/virtuoso/app/claude/mcp_server.py"

@router.post("/chat", response_model=Message)
async def chat(message: Message, request: Request, user=Depends(verify_token)):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    raw_token = auth_header.split(" ")[1]

    try:
        if not mcp_client.session:
            await mcp_client.connect_to_server(SERVER_SCRIPT_PATH)
        response_text = await mcp_client.process_query(message.text, raw_token)
        return {"text": response_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing query: {e}")