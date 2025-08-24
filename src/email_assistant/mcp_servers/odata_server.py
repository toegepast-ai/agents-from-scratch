"""
MCP Server for OData API Integration

This demonstrates how to create an MCP server that can be used with LangGraph
as a standardized way to interact with OData APIs.
"""

import asyncio
import json
import requests
from typing import Any, Dict, Optional, Sequence
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
import mcp.types as types

# Create the MCP server
server = Server("odata-api-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools for OData API interaction."""
    return [
        types.Tool(
            name="query_odata",
            description="Query an OData API using natural language",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query describing what data to retrieve"
                    },
                    "api_url": {
                        "type": "string", 
                        "description": "Base URL of the OData API"
                    },
                    "entity_set": {
                        "type": "string",
                        "description": "The OData entity set to query"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Optional API key for authentication"
                    }
                },
                "required": ["query", "api_url", "entity_set"]
            }
        ),
        types.Tool(
            name="translate_nl_to_odata",
            description="Convert natural language to OData filter syntax",
            inputSchema={
                "type": "object",
                "properties": {
                    "natural_language": {
                        "type": "string",
                        "description": "Natural language description to convert"
                    },
                    "entity_schema": {
                        "type": "object",
                        "description": "Optional schema information about the entity"
                    }
                },
                "required": ["natural_language"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle tool calls for OData operations."""
    
    if name == "query_odata":
        return await query_odata_api(arguments)
    elif name == "translate_nl_to_odata":
        return await translate_nl_to_odata(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")

async def query_odata_api(args: dict) -> list[types.TextContent]:
    """Execute OData query based on natural language input."""
    try:
        query = args["query"]
        api_url = args["api_url"]
        entity_set = args["entity_set"]
        api_key = args.get("api_key")
        
        # Convert natural language to OData filter
        # In a real implementation, you'd use an LLM here
        odata_filter = f"$filter=contains(Description, '{query}')"
        
        # Construct full URL
        full_url = f"{api_url}/{entity_set}?{odata_filter}"
        
        # Set up headers
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # Make the request
        response = requests.get(full_url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        
        # Format response
        if "value" in data:
            items = data["value"]
            result = f"Found {len(items)} items for '{query}':\n"
            for i, item in enumerate(items[:10]):  # Limit to 10 items
                result += f"{i+1}. {json.dumps(item, indent=2)}\n"
        else:
            result = json.dumps(data, indent=2)
            
        return [types.TextContent(type="text", text=result)]
        
    except Exception as e:
        error_msg = f"Error querying OData API: {str(e)}"
        return [types.TextContent(type="text", text=error_msg)]

async def translate_nl_to_odata(args: dict) -> list[types.TextContent]:
    """Convert natural language to OData filter syntax."""
    try:
        nl_query = args["natural_language"]
        
        # This is where you'd implement sophisticated NL->OData translation
        # For now, a simple implementation
        
        # Common patterns
        if "last week" in nl_query.lower():
            filter_expr = "$filter=CreatedDate ge " + "2024-01-01T00:00:00Z"
        elif "contains" in nl_query.lower():
            # Extract the term to search for
            term = nl_query.split("contains")[-1].strip().strip('"\'')
            filter_expr = f"$filter=contains(Description, '{term}')"
        else:
            # Fallback to general text search
            filter_expr = f"$filter=contains(Description, '{nl_query}')"
            
        return [types.TextContent(
            type="text", 
            text=f"OData filter: {filter_expr}"
        )]
        
    except Exception as e:
        error_msg = f"Error translating query: {str(e)}"
        return [types.TextContent(type="text", text=error_msg)]

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="odata-api-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
