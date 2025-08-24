#!/usr/bin/env python
"""
Simplified Gmail ingestion script - LangGraph server execution with proper store management.

This script uses LangGraph server for Agent Inbox integration while avoiding async concurrency issues.
"""

import base64
import json
import argparse
import os
import sys
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from langgraph_sdk import get_sync_client
from dotenv import load_dotenv

load_dotenv()

# Setup paths
_ROOT = Path(__file__).parent.absolute()
_SECRETS_DIR = _ROOT / ".secrets"
TOKEN_PATH = _SECRETS_DIR / "token.json"
# Import the workflow components and rebuild with store
from email_assistant.email_assistant_tweedekamer import overall_workflow
# Also import memory store for proper workflow execution
from langgraph.store.memory import InMemoryStore

load_dotenv()

# Setup paths
_ROOT = Path(__file__).parent.absolute()
_SECRETS_DIR = _ROOT / ".secrets"
TOKEN_PATH = _SECRETS_DIR / "token.json"

def extract_message_part(payload):
    """Extract content from a message part."""
    # If this is multipart, process with preference for text/plain
    if payload.get("parts"):
        # First try to find text/plain part
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain" and part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8")
                
        # If no text/plain found, try text/html
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/html" and part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8")
                
        # If we still haven't found content, recursively check for nested parts
        for part in payload["parts"]:
            content = extract_message_part(part)
            if content:
                return content
    
    # Not multipart, try to get content directly
    if payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data).decode("utf-8")

    return ""

def load_gmail_credentials():
    """Load Gmail credentials from token.json or environment variables."""
    token_data = None
    
    # 1. Try environment variable
    env_token = os.getenv("GMAIL_TOKEN")
    if env_token:
        try:
            token_data = json.loads(env_token)
            print("Using GMAIL_TOKEN environment variable")
        except Exception as e:
            print(f"Could not parse GMAIL_TOKEN environment variable: {str(e)}")
    
    # 2. Try local file as fallback
    if token_data is None:
        if TOKEN_PATH.exists():
            try:
                with open(TOKEN_PATH, "r") as f:
                    token_data = json.load(f)
                print(f"Using token from {TOKEN_PATH}")
            except Exception as e:
                print(f"Could not load token from {TOKEN_PATH}: {str(e)}")
        else:
            print(f"Token file not found at {TOKEN_PATH}")
    
    # If we couldn't get token data from any source, return None
    if token_data is None:
        print("Could not find valid token data in any location")
        return None
    
    try:
        # Create credentials object
        credentials = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/gmail.modify"])
        )
        return credentials
    except Exception as e:
        print(f"Error creating credentials object: {str(e)}")
        return None

def extract_email_data(message):
    """Extract key information from a Gmail message."""
    headers = message['payload']['headers']
    
    # Extract key headers
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
    from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
    to_email = next((h['value'] for h in headers if h['name'] == 'To'), 'Unknown Recipient')
    date = next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown Date')
    
    # Extract message content
    content = extract_message_part(message['payload'])
    
    # Create email data object
    email_data = {
        "from": from_email,
        "to": to_email,
        "subject": subject,
        "body": content,
        "id": message['id'],
        "thread_id": message['threadId']
    }
    
    return email_data

def process_single_email(email_data, graph_name, url="http://127.0.0.1:2024"):
    """Process a single email via LangGraph server with proper store management."""
    print(f"Processing email: {email_data['subject']}")
    print(f"From: {email_data['from']}")
    
    try:
        # Connect to LangGraph server using sync client
        client = get_sync_client(url=url)
        
        # Create a consistent UUID for the thread
        raw_thread_id = email_data["thread_id"]
        thread_id = str(
            uuid.UUID(hex=hashlib.md5(raw_thread_id.encode("UTF-8")).hexdigest())
        )
        print(f"Gmail thread ID: {raw_thread_id} → LangGraph thread ID: {thread_id}")
        
        thread_exists = False
        try:
            # Try to get existing thread info
            thread_info = client.threads.get(thread_id)
            thread_exists = True
            print(f"Found existing thread: {thread_id}")
        except Exception as e:
            # If thread doesn't exist, create it
            print(f"Creating new thread: {thread_id}")
            thread_info = client.threads.create(thread_id=thread_id)
        
        # If thread exists, clean up previous runs to avoid state conflicts
        if thread_exists:
            try:
                # List all runs for this thread
                runs = client.runs.list(thread_id)
                
                # Delete all previous runs to avoid state accumulation
                for run_info in runs:
                    # Handle both dict and object responses safely
                    if isinstance(run_info, dict):
                        run_id = run_info.get('id')
                    else:
                        run_id = getattr(run_info, 'id', None)
                    
                    # Only try to delete if we have a valid run ID
                    if run_id:
                        print(f"Deleting previous run {run_id} from thread {thread_id}")
                        try:
                            client.runs.delete(thread_id, run_id)
                        except Exception as e:
                            print(f"Failed to delete run {run_id}: {str(e)}")
                    else:
                        print(f"Skipping run with invalid ID: {run_info}")
            except Exception as e:
                print(f"Error listing/deleting runs: {str(e)}")
        
        # Update thread metadata with current email ID
        client.threads.update(thread_id, metadata={"email_id": email_data["id"]})
        
        # Create a fresh run for this email - SEQUENTIAL EXECUTION to avoid async conflicts
        print(f"Creating run for thread {thread_id} with graph {graph_name}")
        
        run = client.runs.create(
            thread_id,
            graph_name,
            input={"email_input": email_data},
            config={
                "recursion_limit": 10,  # Increased for tool call spiraling
                "max_concurrency": 1,   # Force single-threaded execution
            }
        )
        
        print(f"✅ Email processing initiated successfully with thread ID: {thread_id}")
        print(f"🔗 Check Agent Inbox for HITL interactions")
        return True
        
    except Exception as e:
        print(f"❌ Error processing email: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def fetch_and_process_emails(args):
    """Fetch emails from Gmail and process them via LangGraph server."""
    # Load Gmail credentials
    credentials = load_gmail_credentials()
    if not credentials:
        print("Failed to load Gmail credentials")
        return 1
        
    # Build Gmail service
    service = build("gmail", "v1", credentials=credentials)
    
    try:
        # Get messages from the specified email address
        email_address = args.email
        
        # Construct Gmail search query
        query = f"to:{email_address} OR from:{email_address}"
        
        # Add time constraint if specified
        if args.minutes_since > 0:
            after = int((datetime.now() - timedelta(minutes=args.minutes_since)).timestamp())
            query += f" after:{after}"
            
        # Only include unread emails unless include_read is True
        if not args.include_read:
            query += " is:unread"
            
        print(f"Gmail search query: {query}")
        
        # Execute the search
        results = service.users().messages().list(userId="me", q=query).execute()
        messages = results.get("messages", [])
        
        if not messages:
            print("No emails found matching the criteria")
            return 0
            
        print(f"Found {len(messages)} emails")
        
        # Process each email SEQUENTIALLY via LangGraph server
        processed_count = 0
        for i, message_info in enumerate(messages):
            # Stop early if requested
            if args.early and i > 0:
                print(f"Early stop after processing {i} emails")
                break
                
            # Get the full message
            message = service.users().messages().get(userId="me", id=message_info["id"]).execute()
            
            # Extract email data
            email_data = extract_email_data(message)
            
            print(f"\n--- Processing email {i+1}/{len(messages)} ---")
            
            # Process the email via LangGraph server
            success = process_single_email(email_data, args.graph_name, args.url)
            
            if success:
                processed_count += 1
                
            # Small delay between emails to avoid any potential conflicts
            print(f"Waiting 3 seconds before next email...")
            import time
            time.sleep(3)
            
        print(f"\n✅ Initiated processing for {processed_count}/{len(messages)} emails")
        print(f"🔗 Check LangGraph UI and Agent Inbox for progress and HITL interactions")
        return 0
        
    except Exception as e:
        print(f"❌ Error processing emails: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Simplified Gmail ingestion - LangGraph server execution")
    
    parser.add_argument(
        "--email", 
        type=str, 
        required=True,
        help="Email address to fetch messages for"
    )
    parser.add_argument(
        "--minutes-since", 
        type=int, 
        default=120,
        help="Only retrieve emails newer than this many minutes"
    )
    parser.add_argument(
        "--graph-name", 
        type=str, 
        default="tweedekamer_assistant",
        help="Name of the LangGraph to use"
    )
    parser.add_argument(
        "--url", 
        type=str, 
        default="http://127.0.0.1:2024",
        help="URL of the LangGraph deployment"
    )
    parser.add_argument(
        "--early", 
        action="store_true",
        help="Early stop after processing one email"
    )
    parser.add_argument(
        "--include-read",
        action="store_true",
        help="Include emails that have already been read"
    )
    return parser.parse_args()

if __name__ == "__main__":
    # Get command line arguments
    args = parse_args()
    
    # Run the simplified script
    exit(fetch_and_process_emails(args))
