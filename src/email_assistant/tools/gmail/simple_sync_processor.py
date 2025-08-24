#!/usr/bin/env python3
"""
SIMPLE SYNCHRONOUS EMAIL PROCESSOR
No async, no threading, no complexity - just process emails one by one.
"""

import base64
import json
import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

# Import the workflow directly - no server, no async
import sys
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from email_assistant.email_assistant_tweedekamer import overall_workflow
from langgraph.store.memory import InMemoryStore

load_dotenv()

# Simple paths
_ROOT = Path(__file__).parent.absolute()
_SECRETS_DIR = _ROOT / ".secrets"
TOKEN_PATH = _SECRETS_DIR / "token.json"

def get_gmail_service():
    """Get Gmail API service - simple and direct."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"No token found at {TOKEN_PATH}")
    
    with open(TOKEN_PATH, 'r') as f:
        token_data = json.load(f)
    
    creds = Credentials.from_authorized_user_info(token_data)
    return build('gmail', 'v1', credentials=creds)

def extract_email_body(payload):
    """Extract email body - simple recursive approach."""
    if payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors='ignore')
        # If no text/plain, try first part with data
        for part in payload["parts"]:
            if part.get("body", {}).get("data"):
                data = part["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors='ignore')
    elif payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data).decode("utf-8", errors='ignore')
    
    return "No readable content"

def process_single_email(email_id, service):
    """Process one email completely synchronously."""
    print(f"\n🔄 Processing email: {email_id}")
    
    try:
        # Get email details
        message = service.users().messages().get(userId='me', id=email_id).execute()
        
        # Extract headers
        headers = {h['name']: h['value'] for h in message['payload'].get('headers', [])}
        subject = headers.get('Subject', 'No Subject')
        from_addr = headers.get('From', 'Unknown')
        to_addr = headers.get('To', 'Unknown')
        
        # Extract body
        body = extract_email_body(message['payload'])
        
        print(f"📧 Subject: {subject}")
        print(f"👤 From: {from_addr}")
        print(f"📝 Body: {body[:100]}...")
        
        # Create email input
        email_input = {
            'from': from_addr,
            'to': to_addr,
            'subject': subject,
            'body': body,
            'id': email_id,
            'thread_id': message.get('threadId', email_id)
        }
        
        # Create fresh memory store for this email
        store = InMemoryStore()
        
        # Run workflow SYNCHRONOUSLY - no server, no async
        print("🚀 Running workflow...")
        
        # Configure workflow for sync execution
        config = {
            "recursion_limit": 5,  # Very low limit
            "configurable": {}
        }
        
        # Execute workflow step by step
        compiled_workflow = overall_workflow.compile(store=store)
        result = compiled_workflow.invoke(
            {"email_input": email_input},
            config=config
        )
        
        print(f"✅ Email {email_id} processed successfully")
        print(f"📊 Result: {result.get('classification_decision', 'unknown')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error processing email {email_id}: {e}")
        return False

def main():
    """Main function - get emails and process them one by one."""
    print("🔧 Simple Synchronous Email Processor")
    
    # Get specific email ID from command line or use default
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', help='Specific email ID to process')
    parser.add_argument('--query', default='is:unread', help='Gmail query')
    args = parser.parse_args()
    
    # Get Gmail service
    service = get_gmail_service()
    
    if args.email:
        # Process single specific email
        success = process_single_email(args.email, service)
        print(f"\n🎯 Single email processing: {'✅ Success' if success else '❌ Failed'}")
    else:
        # Get unread emails
        print(f"📥 Searching for emails with query: {args.query}")
        results = service.users().messages().list(userId='me', q=args.query).execute()
        messages = results.get('messages', [])
        
        if not messages:
            print("📭 No emails found")
            return
        
        print(f"📬 Found {len(messages)} emails")
        
        # Process each email one by one
        successful = 0
        for i, message in enumerate(messages):
            email_id = message['id']
            print(f"\n--- Processing {i+1}/{len(messages)} ---")
            
            if process_single_email(email_id, service):
                successful += 1
            
            # Simple delay between emails
            import time
            time.sleep(2)
        
        print(f"\n🎯 Summary: {successful}/{len(messages)} emails processed successfully")

if __name__ == "__main__":
    main()
