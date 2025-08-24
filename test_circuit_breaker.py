#!/usr/bin/env python3
"""
Test the circuit breaker fix with specific email ID
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from langgraph_sdk import get_sync_client
from email_assistant.utils import parse_gmail

load_dotenv()

def test_circuit_breaker(email_id="198d78298b0ec161"):
    """Test the circuit breaker with a specific problematic email."""
    
    # The email data we know causes spiraling
    email_input = {
        'from': 'Jacques Willemen <jjwillemen@pm.me>',
        'to': '"tweedekamer.datainbox@gmail.com" <tweedekamer.datainbox@gmail.com>',
        'subject': 'Vraagje over debatten varkens',
        'body': 'Hallo,\r\nWanneer werd er in de kamer voor het laatst gesproken over de overlast door varkensteelt in Brabant?\r\n\r\nVerzonden met Proton Mail Android\r\n',
        'id': email_id,
        'thread_id': email_id
    }
    
    print("🧪 Testing circuit breaker with problematic email...")
    print(f"📧 Subject: {email_input['subject']}")
    
    try:
        # Connect to LangGraph server
        client = get_sync_client(url="http://127.0.0.1:2024")
        
        # Generate thread ID and create thread
        import uuid
        thread_id = str(uuid.uuid4())
        
        # Create thread first
        thread = client.threads.create(thread_id=thread_id)
        print(f"🔗 Created thread: {thread_id}")
        
        # Create the run with low recursion limit
        run_response = client.runs.create(
            thread_id=thread_id,
            assistant_id="tweedekamer_assistant",
            input={"email_input": email_input},
            config={
                "recursion_limit": 10,  # Low limit to test circuit breaker
                "max_concurrency": 1
            }
        )
        
        run_id = run_response["run_id"]
        print(f"🚀 Started run: {run_id}")
        
        # Wait for completion
        import time
        while True:
            run_status_response = client.runs.get(thread_id=thread_id, run_id=run_id)
            status = run_status_response.get("status", "unknown")
            print(f"📊 Status: {status}")
            
            if status in ["error", "success", "interrupt"]:
                break
            
            time.sleep(2)
        
        print(f"✅ Final status: {status}")
        
        if status == "error":
            print("❌ Run failed - circuit breaker didn't work")
        elif status == "interrupt":
            print("🛑 Run interrupted - check Agent Inbox for HITL")
        else:
            print("🎯 Run completed successfully!")
            
        return status
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return "error"

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', default='198d78298b0ec161', help='Email ID to test')
    args = parser.parse_args()
    
    result = test_circuit_breaker(args.email)
    print(f"\n🎯 Test result: {result}")
