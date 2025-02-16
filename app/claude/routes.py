from fastapi import APIRouter, Depends, HTTPException
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

# Input and Output models
class Message(BaseModel):
    text: str

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic(api_key=CLAUDE_KEY)

    async def connect_to_server(self, server_script_path: str):
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

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

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        response = await self.session.list_tools()
        available_tools = [{ 
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        } for tool in response.tools]

        # Initial Claude API call
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=messages,
            tools=available_tools
        )

        # Process response and handle tool calls
        tool_results = []
        final_text = []

        for content in response.content:
            if content.type == 'text':
                final_text.append(content.text)
            elif content.type == 'tool_use':
                tool_name = content.name
                tool_args = content.input
                
                # Execute tool call
                result = await self.session.call_tool(tool_name, tool_args)
                tool_results.append({"call": tool_name, "result": result})
                final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

                # Continue conversation with tool results
                if hasattr(content, 'text') and content.text:
                    messages.append({
                    "role": "assistant",
                    "content": content.text
                    })
                messages.append({
                    "role": "user", 
                    "content": result.content
                })

                # Get next response from Claude
                response = self.anthropic.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    messages=messages,
                )

                final_text.append(response.content[0].text)

        return "\n".join(final_text)


    async def cleanup(self):
        await self.exit_stack.aclose()


# Initialize MCP Client and server connection
mcp_client = MCPClient()
SERVER_SCRIPT_PATH = "/home/sushi/Desktop/virtuoso/app/claude/mcp_server.py"  # Update the path accordingly

@router.post("/chat", response_model=Message)
async def chat(message: Message, user=Depends(verify_token)):
    # Retrieve the user from the database
    query = users.select().where(users.c.username == user['sub'])
    db_user = await database.fetch_one(query)

    if not db_user:
        raise HTTPException(status_code=400, detail="User not found")

    try:
        # Ensure connection to the server
        if not mcp_client.session:
            await mcp_client.connect_to_server(SERVER_SCRIPT_PATH)
        # Process the query through MCP Client
        response_text = await mcp_client.process_query(message.text)
        return {"text": response_text}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing query: {e}")

